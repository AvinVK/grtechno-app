from app.extensions import db
from app.models import RoleModule, User
from conftest import make_user, signed_in


def names(client):
    return [m["name"] for m in client.get("/api/modules").get_json()["modules"]]


# ---------- who gets which role ----------

def test_new_users_default_to_field_sales_and_the_admin_is_admin(user, admin):
    assert user.role_key == "sales_field" and admin.role_key == "admin"
    assert admin.sees_all and not user.sees_all


def test_admin_adds_a_user_with_a_role(admin_client):
    res = admin_client.post("/api/users", json={"name": "Meena Patil", "role": "project_manager"})
    assert res.status_code == 201
    assert res.get_json()["user"]["role"] == "project_manager"
    assert res.get_json()["user"]["role_name"] == "Project manager"
    listing = admin_client.get("/api/users").get_json()
    assert "admin" not in [r["key"] for r in listing["roles"]]                       # the one admin cannot be assigned
    assert {"sales_field", "project_manager", "accounts", "supervisor"} <= {r["key"] for r in listing["roles"]}


def test_role_rules_on_adding_a_user(admin_client):
    assert admin_client.post("/api/users", json={"name": "Nope", "role": "admin"}).status_code == 422
    assert admin_client.post("/api/users", json={"name": "Nope", "role": "ghost"}).status_code == 422
    default = admin_client.post("/api/users", json={"name": "No Role Given"}).get_json()
    assert default["user"]["role"] == "sales_field"


def test_admin_can_change_a_users_role(admin_client, user, client):
    assert names(client) == ["Leads", "Attendance"]
    res = admin_client.post(f"/api/users/{user.code}/role", json={"role": "project_manager"})
    assert res.status_code == 200 and res.get_json()["user"]["role"] == "project_manager"
    assert names(client) == ["Clients", "Projects", "Attendance"]                      # menu follows the role at once
    assert admin_client.post(f"/api/users/{user.code}/role", json={"role": "admin"}).status_code == 422
    assert admin_client.post(f"/api/users/{user.code}/role", json={"role": "ghost"}).status_code == 422


def test_admins_role_is_fixed_and_only_the_admin_sets_roles(admin_client, admin, client, user):
    assert admin_client.post(f"/api/users/{admin.code}/role", json={"role": "sales_field"}).status_code == 400
    assert client.post(f"/api/users/{user.code}/role", json={"role": "accounts"}).status_code == 403


# ---------- what each role can open ----------

def test_sales_cannot_open_clients_or_projects(client):
    assert names(client) == ["Leads", "Attendance"]
    for path in ("/clients", "/projects", "/api/clients", "/api/projects"):
        assert client.get(path).status_code == 403, path


def test_project_manager_cannot_open_lead_desk(manager_client):
    assert names(manager_client) == ["Clients", "Projects", "Attendance"]
    assert manager_client.get("/export.csv").status_code == 403
    assert manager_client.get("/api/state").status_code == 403
    assert manager_client.get("/api/projects").status_code == 200


def test_home_page_sends_people_to_a_service_they_can_use(manager_client, client, admin_client):
    home = manager_client.get("/")
    assert home.status_code == 302 and home.headers["Location"].endswith("/clients")   # first of their services
    assert client.get("/").status_code == 200                                          # sales: Leads itself
    assert admin_client.get("/").status_code == 200


def test_supervisor_can_only_open_attendance(app):
    supervisor = signed_in(app, make_user("Site Sam", role="supervisor"))
    assert names(supervisor) == ["Attendance"]
    assert supervisor.get("/api/projects").status_code == 403
    home = supervisor.get("/")
    assert home.status_code == 302 and home.headers["Location"].endswith("/attendance")


def test_admin_opens_everything(admin_client):
    assert names(admin_client) == ["Leads", "Clients", "Projects", "Attendance"]


def test_roles_are_editable_in_the_database(app):
    supervisor = signed_in(app, make_user("Site Sam", role="supervisor"))
    assert supervisor.get("/api/projects").status_code == 403
    db.session.add(RoleModule(role_key="supervisor", module_key="projects"))
    db.session.commit()
    assert supervisor.get("/api/projects").status_code == 200
    assert names(supervisor) == ["Projects", "Attendance"]


def test_a_user_without_a_role_can_open_nothing(app, user):
    db.session.get(User, user.code).role_key = None
    db.session.commit()
    assert names(signed_in(app, user)) == []


# ---------- site trades and Accountant ----------

def test_trades_sign_in_to_attendance_only(app):
    from conftest import make_user, signed_in
    for role in ("welder", "fitter", "helper", "alarm_technician"):
        worker = signed_in(app, make_user(f"Test {role}", role=role))
        assert names(worker) == ["Attendance"], role
        assert worker.get("/attendance").status_code == 200
        for url in ("/api/state", "/api/clients", "/api/projects"):
            assert worker.get(url).status_code == 403, (role, url)
        assert worker.get("/api/attendance/team").status_code == 403          # only their own attendance


def test_admin_can_give_the_new_roles_and_accounts_is_now_accountant(admin_client, app):
    from conftest import make_user
    roles = {r["key"]: r["name"] for r in admin_client.get("/api/users").get_json()["roles"]}
    assert roles["accounts"] == "Accountant"
    assert {"welder", "fitter", "helper", "alarm_technician"} <= roles.keys()
    with app.app_context():
        code = make_user("Sunny Welder").code
    res = admin_client.post(f"/api/users/{code}/role", json={"role": "welder"})
    assert res.status_code == 200 and res.get_json()["user"]["role_name"] == "Welder"


# ---------- Sub-admin: clients and projects, scoped to assigned state(s) ----------

def test_states_list_is_offered_and_sub_admin_needs_at_least_one(admin_client, app):
    from conftest import make_user
    states = admin_client.get("/api/users").get_json()["states"]
    assert "Jharkhand" in states and "Maharashtra" in states

    # Adding one with no states: refused.
    bad = admin_client.post("/api/users", json={"name": "No States", "role": "sub_admin"})
    assert bad.status_code == 422

    ok = admin_client.post("/api/users", json={
        "name": "Reena Sub", "role": "sub_admin", "states": ["Jharkhand", "Jharkhand", "Not-a-state"],
    })
    assert ok.status_code == 201
    assert ok.get_json()["user"]["states"] == ["Jharkhand"]                  # deduped, and junk dropped

    with app.app_context():
        code = make_user("Later Sub").code
    assert admin_client.post(f"/api/users/{code}/role", json={"role": "sub_admin"}).status_code == 422
    promoted = admin_client.post(f"/api/users/{code}/role", json={"role": "sub_admin", "states": ["Odisha"]})
    assert promoted.status_code == 200 and promoted.get_json()["user"]["states"] == ["Odisha"]

    changed = admin_client.post(f"/api/users/{code}/states", json={"states": ["Odisha", "Karnataka"]})
    assert changed.status_code == 200 and sorted(changed.get_json()["user"]["states"]) == ["Karnataka", "Odisha"]
    assert admin_client.post(f"/api/users/{code}/states", json={"states": []}).status_code == 422

    with app.app_context():
        not_sub = make_user("Not A Sub Admin", role="sales_field").code
    assert admin_client.post(f"/api/users/{not_sub}/states", json={"states": ["Odisha"]}).status_code == 400


def test_sub_admin_sees_only_their_assigned_states(app, admin_client):
    from conftest import make_user
    pid = admin_client.post("/api/projects", json={"new_client_name": "Jharkhand Co", "status": "running"}).get_json()["project"]["id"]
    cid = admin_client.get(f"/api/projects/{pid}").get_json()["client"]["id"]
    admin_client.patch(f"/api/projects/{pid}", json={"title": "Jharkhand Co", "site_state": "Jharkhand"})
    admin_client.patch(f"/api/clients/{cid}", json={"state": "Jharkhand"})

    pid2 = admin_client.post("/api/projects", json={"new_client_name": "Maha Co", "status": "running"}).get_json()["project"]["id"]
    cid2 = admin_client.get(f"/api/projects/{pid2}").get_json()["client"]["id"]
    admin_client.patch(f"/api/projects/{pid2}", json={"title": "Maha Co", "site_state": "Maharashtra"})
    admin_client.patch(f"/api/clients/{cid2}", json={"state": "Maharashtra"})

    sub = make_user("Reena Sub", role="sub_admin")
    sub_client = signed_in(app, sub)
    assert sub_client.get("/api/projects").get_json()["projects"] == []      # no state assigned yet: sees nothing
    assert sub_client.get(f"/api/projects/{pid}").status_code == 404

    admin_client.post(f"/api/users/{sub.code}/states", json={"states": ["Jharkhand"]})
    sub_client = signed_in(app, sub)
    project_ids = {p["id"] for p in sub_client.get("/api/projects").get_json()["projects"]}
    assert project_ids == {pid}
    assert sub_client.get(f"/api/projects/{pid}").status_code == 200
    assert sub_client.get(f"/api/projects/{pid2}").status_code == 404

    client_ids = {c["id"] for c in sub_client.get("/api/clients").get_json()["clients"]}
    assert client_ids == {cid}
    assert sub_client.get(f"/api/clients/{cid}").status_code == 200
    assert sub_client.get(f"/api/clients/{cid2}").status_code == 404

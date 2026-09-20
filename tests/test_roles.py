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
    assert names(client) == ["Lead desk"]
    res = admin_client.post(f"/api/users/{user.code}/role", json={"role": "project_manager"})
    assert res.status_code == 200 and res.get_json()["user"]["role"] == "project_manager"
    assert names(client) == ["Clients", "Projects"]                                   # menu follows the role at once
    assert admin_client.post(f"/api/users/{user.code}/role", json={"role": "admin"}).status_code == 422
    assert admin_client.post(f"/api/users/{user.code}/role", json={"role": "ghost"}).status_code == 422


def test_admins_role_is_fixed_and_only_the_admin_sets_roles(admin_client, admin, client, user):
    assert admin_client.post(f"/api/users/{admin.code}/role", json={"role": "sales_field"}).status_code == 400
    assert client.post(f"/api/users/{user.code}/role", json={"role": "accounts"}).status_code == 403


# ---------- what each role can open ----------

def test_sales_cannot_open_clients_or_projects(client):
    assert names(client) == ["Lead desk"]
    for path in ("/clients", "/projects", "/api/clients", "/api/projects"):
        assert client.get(path).status_code == 403, path


def test_project_manager_cannot_open_lead_desk(manager_client):
    assert names(manager_client) == ["Clients", "Projects"]
    assert manager_client.get("/export.csv").status_code == 403
    assert manager_client.get("/api/state").status_code == 403
    assert manager_client.get("/api/projects").status_code == 200


def test_home_page_sends_people_to_a_service_they_can_use(manager_client, client, admin_client):
    home = manager_client.get("/")
    assert home.status_code == 302 and home.headers["Location"].endswith("/clients")   # first of their services
    assert client.get("/").status_code == 200                                          # sales: Lead desk itself
    assert admin_client.get("/").status_code == 200


def test_supervisor_has_no_services_yet(app):
    supervisor = signed_in(app, make_user("Site Sam", role="supervisor"))
    assert names(supervisor) == []
    assert supervisor.get("/api/projects").status_code == 403
    home = supervisor.get("/")
    assert home.status_code == 200 and b"cannot open any services yet" in home.data      # a message, not an error page


def test_admin_opens_everything(admin_client):
    assert names(admin_client) == ["Lead desk", "Clients", "Projects"]


def test_roles_are_editable_in_the_database(app):
    supervisor = signed_in(app, make_user("Site Sam", role="supervisor"))
    assert supervisor.get("/api/projects").status_code == 403
    db.session.add(RoleModule(role_key="supervisor", module_key="projects"))
    db.session.commit()
    assert supervisor.get("/api/projects").status_code == 200
    assert names(supervisor) == ["Projects"]


def test_a_user_without_a_role_can_open_nothing(app, user):
    db.session.get(User, user.code).role_key = None
    db.session.commit()
    assert names(signed_in(app, user)) == []

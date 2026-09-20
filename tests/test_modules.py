from app.extensions import db
from app.models import Module, RoleModule
from app.modules import module_required


def add_module(key, name, path, icon="grid", order=2, active=True, admin_only=False):
    db.session.add(Module(key=key, name=name, icon=icon, path=path, sort_order=order, is_active=active, admin_only=admin_only))
    db.session.commit()


def grant(role, *module_keys):
    for key in module_keys:
        db.session.add(RoleModule(role_key=role, module_key=key))
    db.session.commit()


def menu_names(client):
    return [m["name"] for m in client.get("/api/modules").get_json()["modules"]]


# ---------- what the menu lists ----------

def test_menu_lists_active_services_in_order(client):
    add_module("attendance", "Attendance", "/attendance", icon="attendance", order=6)
    add_module("manpower", "Manpower", "/manpower", icon="manpower", order=5)
    add_module("old", "Retired", "/old", order=7, active=False)
    grant("sales_field", "attendance", "manpower", "old")
    assert menu_names(client) == ["Lead desk", "Manpower", "Attendance"]      # by sort_order, retired one hidden


def test_admin_only_services_are_hidden_from_regular_users(client, admin_client):
    add_module("payroll", "Payroll", "/payroll", admin_only=True)
    grant("sales_field", "payroll")
    assert "Payroll" not in menu_names(client)
    assert "Payroll" in menu_names(admin_client)


def test_menu_needs_sign_in(anon):
    assert anon.get("/api/modules").status_code == 401


def test_page_has_the_menu_button_and_panel(client, user):
    add_module("attendance", "Attendance", "/attendance", icon="attendance")
    grant("sales_field", "attendance")
    html = client.get("/").get_data(as_text=True)
    assert 'id="menu-btn"' in html and 'aria-expanded="false"' in html
    assert 'id="sidebar"' in html and "Attendance" in html and "Sign out" in html
    assert user.userid in html                                                   # who is signed in
    assert 'href="/attendance"' in html
    # the service you are on is marked
    assert 'href="/" aria-current="page"' in html


def test_users_and_roles_is_only_in_the_admin_menu(client, admin_client, manager_client, accounts_client):
    for who in (client, manager_client, accounts_client):                        # every non-admin role
        html = who.get("/").get_data(as_text=True)
        assert 'href="/users"' not in html and "Users &amp; roles" not in html and ">Manage<" not in html
        assert who.get("/users").status_code == 403
        assert who.get("/api/users").status_code == 403
    html = admin_client.get("/").get_data(as_text=True)
    assert 'href="/users"' in html and "Users &amp; roles" in html


def test_login_page_has_no_menu(anon):
    html = anon.get("/login").get_data(as_text=True)
    assert 'id="menu-btn"' not in html and 'id="sidebar"' not in html


# ---------- the switch is enforced on the server, not only hidden ----------

def test_turning_lead_desk_off_blocks_its_pages_and_api(client):
    Module.query.filter_by(key="leads").update({"is_active": False})
    db.session.commit()
    home = client.get("/")                                          # nothing else to open, so a message, not an error
    assert home.status_code == 200 and b"cannot open any services yet" in home.data
    assert client.get("/export.csv").status_code == 404
    assert client.get("/api/state").status_code == 404
    assert client.post("/api/leads", json={"company": "X"}).status_code == 404
    assert "Lead desk" not in menu_names(client)


def test_admin_only_service_is_enforced(client, admin_client):
    Module.query.filter_by(key="leads").update({"admin_only": True})
    db.session.commit()
    assert client.get("/api/state").status_code == 403
    assert admin_client.get("/api/state").status_code == 200


def test_module_required_guards_a_new_service(app, client, admin_client):
    add_module("attendance", "Attendance", "/attendance", icon="attendance")
    grant("sales_field", "attendance")

    @app.get("/attendance")
    @module_required("attendance")
    def attendance_page():
        return "attendance"

    assert client.get("/attendance").get_data(as_text=True) == "attendance"
    Module.query.filter_by(key="attendance").update({"admin_only": True})
    db.session.commit()
    assert client.get("/attendance").status_code == 403
    assert admin_client.get("/attendance").status_code == 200
    Module.query.filter_by(key="attendance").update({"is_active": False})
    db.session.commit()
    assert admin_client.get("/attendance").status_code == 404

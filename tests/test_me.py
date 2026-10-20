"""The Me hub (/me): the phone's replacement for the side menu."""

from datetime import timedelta

from app.extensions import db
from app.models import Attendance, Client, Lead, Project, utcnow
from app.timeutil import today_local

from conftest import make_user, signed_in


def add_project(admin_client, name="Orchid Heights"):
    res = admin_client.post("/api/projects", json={"new_client_name": name})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["project"]["id"]


def stocked_material(admin_client, name="Cement"):
    res = admin_client.post("/api/inventory/materials", json={"name": name, "unit": "bags", "quantity": 20, "rate": 10})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["material"]["id"]


def test_me_needs_sign_in(anon):
    assert anon.get("/me").status_code == 302


def test_me_shows_who_you_are_and_signs_out(client, user):
    # Name/userid live in the profile menu (View profile, see test_api_me_reports_...) rather than
    # the page body now - Sign out is still a plain button on the page itself.
    html = client.get("/me").get_data(as_text=True)
    assert 'action="/logout"' in html and 'name="csrf"' in html and ">Sign out</button>" in html


def test_manage_is_for_the_admin_only(client, admin_client):
    assert "Manage" not in client.get("/me").get_data(as_text=True)
    html = admin_client.get("/me").get_data(as_text=True)
    assert 'id="me-manage"' in html
    # Attendance sheet is no longer a Manage row - it's reached from the Attendance page itself
    # (kohal, 2026-10-20), see test_attendance.py/test_workforce.py for that link's own gating.
    for href in ("/users", "/workforce"):
        assert f'href="{href}"' in html
    assert 'href="/attendance-sheet"' not in html
    # Hiding the links is not the access control - the pages still refuse anyone else.
    for url in ("/users", "/workforce", "/attendance-sheet"):
        assert client.get(url).status_code == 403


def test_a_tile_per_service_with_cheap_summaries(app, admin_client, admin):
    with app.app_context():
        c = Client(name="Kalyani")
        db.session.add_all([c, Project(client=c, title="A", status="running"), Project(client=c, title="B", status="planned")])
        monday = today_local() - timedelta(days=today_local().weekday())
        db.session.add(Attendance(user_code=admin.code, work_date=monday, check_in_at=utcnow()))
        db.session.commit()
    html = admin_client.get("/me").get_data(as_text=True)
    for path in ("/", "/clients", "/projects", "/attendance"):
        assert f'class="me-tile" href="{path}"' in html
    assert "0 open" in html and "1 client<" in html and "1 running" in html
    assert "Team attendance" in html and "checked in today" in html        # the admin's tile: the team, not a week
    assert 'id="me-today"' not in html                                     # no check-in card - that's the Attendance tab's job now


def test_the_leads_tile_adds_an_overdue_count_once_there_is_one(app, admin_client):
    with app.app_context():
        db.session.add(Lead(company="On time", stage="New enquiry", follow_up_date=today_local()))
        db.session.commit()
    html = admin_client.get("/me").get_data(as_text=True)
    assert "1 open</span>" in html and "overdue" not in html         # nothing overdue yet: just the plain count

    with app.app_context():
        db.session.add(Lead(company="Late", stage="New enquiry", follow_up_date=today_local() - timedelta(days=3)))
        db.session.commit()
    html = admin_client.get("/me").get_data(as_text=True)
    assert "2 open · 1 overdue</span>" in html


def test_everyone_else_gets_their_week_on_the_attendance_tile_not_a_today_card(app, client, user):
    """The Me hub used to duplicate today's check-in card here too - removed (kohal, 2026-10-16) now that
    the bottom nav has its own Attendance tab for that; the tile here just keeps its one-line summary."""
    with app.app_context():
        monday = today_local() - timedelta(days=today_local().weekday())
        db.session.add(Attendance(user_code=user.code, work_date=monday, check_in_at=utcnow()))
        db.session.commit()
    html = client.get("/me").get_data(as_text=True)
    assert 'id="me-today"' not in html and "attendance-core.js" not in html
    assert "me.js" in html                                              # still needed for the profile menu
    assert "Your attendance" in html and "1 day this week" in html


def test_bottom_nav_me_goes_to_the_hub(client):
    html = client.get("/").get_data(as_text=True)
    assert 'class="bottom-nav-item" href="/me"' in html
    assert "data-open-menu" not in html
    assert "appbar-back" not in html                               # Leads has the bottom nav instead


def test_profile_button_is_on_every_me_page(client, admin_client):
    for c in (client, admin_client):
        assert 'id="profile-btn"' in c.get("/me").get_data(as_text=True)


def test_api_me_reports_name_userid_designation_and_phone(client, user):
    data = client.get("/api/me").get_json()
    assert data["name"] == user.name and data["userid"] == user.userid and data["phone"] == ""
    assert data["designation"] == (user.role.name if user.role else None)


def test_api_me_requires_sign_in(anon):
    assert anon.get("/api/me").status_code == 401


def test_a_person_can_set_their_own_phone(client):
    res = client.patch("/api/me", json={"phone": "9876543210"})
    assert res.status_code == 200 and res.get_json()["phone"] == "9876543210"
    assert client.get("/api/me").get_json()["phone"] == "9876543210"


def test_phone_is_too_long_is_rejected(client):
    res = client.patch("/api/me", json={"phone": "9" * 41})
    assert res.status_code == 400 and "fields" in res.get_json()


def test_api_me_patch_requires_a_phone_key(client):
    assert client.patch("/api/me", json={}).status_code == 400


def test_every_page_keeps_the_bottom_tabs_with_me_current(client, admin_client):
    # Clients/Projects claim their own tab as current and skip the back chevron since the tabs already
    # get you back; Inventory and Attendance claim their tab too but keep the chevron anyway (Inventory goes
    # deeper than one level - list -> material -> stock-in/issue; Attendance's own history view does too);
    # every other pushed screen defaults to Me and keeps the chevron alongside the tabs.
    current_tab = {"/clients": '/clients" aria-current="page"', "/projects": '/projects" aria-current="page"',
                    "/inventory": '/inventory" aria-current="page"', "/attendance": '/attendance" aria-current="page"'}
    no_back = {"/clients", "/projects"}
    for who, url in ((client, "/attendance"), (admin_client, "/users"), (admin_client, "/workforce"),
                     (admin_client, "/attendance-sheet"), (admin_client, "/clients"), (admin_client, "/projects"),
                     (admin_client, "/inventory")):
        html = who.get(url).get_data(as_text=True)
        assert 'class="bottom-nav"' in html and current_tab.get(url, 'href="/me" aria-current="page"') in html, url
        assert 'href="/#active"' in html and "has-bottom-nav" in html, url
        assert ('id="appbar-back"' in html) == (url not in no_back), url


def test_without_leads_other_pages_still_get_the_bottom_tabs(accounts_client):
    """A role with no Leads access (kohal, 2026-10-16: used to mean no bottom nav at all on any page,
    stranding a role like Accountant or Welder with only the appbar back arrow) still gets the tabs it does
    have (Clients here), with Leads itself simply absent - never a tab here that just 403s."""
    html = accounts_client.get("/clients").get_data(as_text=True)
    assert 'class="bottom-nav"' in html and '/clients" aria-current="page"' in html
    assert 'href="/#active"' not in html and 'aria-label="Leads"' not in html   # no Leads tab for this role
    assert "appbar-back" not in html                                            # Clients claims its own tab
    assert "appbar-back" not in accounts_client.get("/me").get_data(as_text=True)


def test_hub_keeps_the_bottom_tabs_leading_back_into_leads(client):
    html = client.get("/me").get_data(as_text=True)
    assert 'href="/#active"' in html
    assert 'href="/me" aria-current="page"' in html and "has-bottom-nav" in html


def test_leads_page_tabs_still_switch_in_place(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="#active"' in html and 'href="/#active"' not in html


def test_hub_shows_the_due_count_on_the_active_tab(app, client, user):
    from app.models import Lead
    with app.app_context():
        db.session.add(Lead(company="Due Co", owner_code=user.code, stage="New enquiry", follow_up_date=today_local()))
        db.session.commit()
    assert '<b class="nav-badge">1</b>' in client.get("/me").get_data(as_text=True)


def test_bottom_tabs_show_whatever_modules_a_role_has_without_leads(app, manager_client):
    html = manager_client.get("/me").get_data(as_text=True)          # project managers have no Leads service
    assert 'class="bottom-nav"' in html and "page-plain" in html
    assert 'aria-label="Leads"' not in html
    assert 'href="/projects" aria-current="page"' not in html        # Me, not Projects, is current here
    assert "Attendance</span>" in html and "Projects</span>" in html


def test_a_role_with_no_modules_at_all_still_gets_the_me_tab(app):
    """A role added on the fly (see app/roles.py's add_role - "no module access yet") that nobody has set up
    access for yet: used to land on a dead "no services" page with no way out at all (kohal, 2026-10-16,
    screenshot). Now still gets a bottom nav with just Me, so there's always somewhere to go."""
    from app.models import Role
    with app.app_context():
        db.session.add(Role(key="brand_new_role", name="Brand New Role", sees_all=False))
        db.session.commit()
    stranded = make_user("Nobody Yet", role="brand_new_role")
    c = signed_in(app, stranded)
    html = c.get("/").get_data(as_text=True)
    assert "You cannot open any services yet" in html
    assert 'class="bottom-nav"' in html and 'href="/me" aria-current="page"' in html
    assert 'aria-label="Leads"' not in html and "Projects</span>" not in html and "Attendance</span>" not in html


# ---------- material approvals on the Me hub (kohal, 2026-10-16: "i want to see the requests in me tab") ----------

def test_a_pending_issue_request_no_longer_shows_on_the_me_hub(app, client, admin_client):
    """kohal, 2026-10-17: issue approval moved to its own tab inside Inventory - the Me hub's own section
    only ever shows a pending stock-in now (see the next test), not an issue request, even for a role (here,
    a project manager) that used to see it there."""
    pid = add_project(admin_client)
    mat_id = stocked_material(admin_client)
    manager = make_user("Priya Manager", role="project_manager")
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    accounts_client = signed_in(app, make_user("Anil Accounts", role="accounts"))
    accounts_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})

    pm_client = signed_in(app, manager)
    assert pm_client.get("/api/me/material-approvals").get_json()["approvals"] == []


def test_an_accountant_sees_a_pending_stock_in_they_can_approve(app):
    director = signed_in(app, make_user("Dilip Director", role="company_director"))
    mat = director.post("/api/inventory/materials", json={"name": "Cement", "unit": "bags"}).get_json()["material"]
    director.post(f"/api/inventory/materials/{mat['id']}/stock-in", json={"quantity": 10, "rate": 5})

    accounts_client = signed_in(app, make_user("Anil Accounts", role="accounts"))
    data = accounts_client.get("/api/me/material-approvals").get_json()
    assert len(data["approvals"]) == 1
    row = data["approvals"][0]
    assert row["kind"] == "in" and row["material_id"] == mat["id"] and row["requested_by"] == "Dilip Director"

    # the director themselves can't approve their own stock-in
    assert director.get("/api/me/material-approvals").get_json()["approvals"] == []


def test_material_approvals_is_empty_for_someone_with_nothing_to_approve(app, client, admin_client):
    pid = add_project(admin_client)
    mat_id = stocked_material(admin_client)
    accounts_client = signed_in(app, make_user("Anil Accounts", role="accounts"))
    accounts_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})

    welder_client = signed_in(app, make_user("Wendy Welder", role="welder"))
    assert welder_client.get("/api/me/material-approvals").get_json()["approvals"] == []

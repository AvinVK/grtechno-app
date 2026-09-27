"""The Me hub (/me): the phone's replacement for the side menu."""

from datetime import timedelta

from app.extensions import db
from app.models import Attendance, Client, Project, utcnow
from app.timeutil import today_local


def test_me_needs_sign_in(anon):
    assert anon.get("/me").status_code == 302


def test_me_shows_who_you_are_and_signs_out(client, user):
    html = client.get("/me").get_data(as_text=True)
    assert user.name in html and user.userid in html and "· Admin" not in html
    assert 'action="/logout"' in html and 'name="csrf"' in html and ">Sign out</button>" in html


def test_manage_is_for_the_admin_only(client, admin_client):
    assert "Manage" not in client.get("/me").get_data(as_text=True)
    html = admin_client.get("/me").get_data(as_text=True)
    assert "· Admin" in html and 'id="me-manage"' in html
    for href in ("/users", "/workforce", "/attendance-sheet"):
        assert f'href="{href}"' in html
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
    assert "0 open" in html and "1 client<" in html and "1 running" in html and "1 day this week" in html
    assert 'id="me-today"' in html and "attendance-core.js" in html and "me.js" in html


def test_no_today_card_without_attendance(app, admin_client):
    from app.models import Module
    with app.app_context():
        db.session.get(Module, "attendance").is_active = False
        db.session.commit()
    html = admin_client.get("/me").get_data(as_text=True)
    assert 'id="me-today"' not in html and "me.js" not in html


def test_bottom_nav_me_goes_to_the_hub(client):
    html = client.get("/").get_data(as_text=True)
    assert 'class="bottom-nav-item" href="/me"' in html
    assert "data-open-menu" not in html
    assert "hub-back" not in html                                  # Leads has the bottom nav instead


def test_other_pages_get_a_way_back_to_the_hub(client, admin_client):
    assert 'class="icon-btn hub-back" href="/me"' in client.get("/attendance").get_data(as_text=True)
    assert 'class="icon-btn hub-back" href="/me"' in admin_client.get("/users").get_data(as_text=True)
    assert "hub-back" not in client.get("/me").get_data(as_text=True)


def test_hub_keeps_the_bottom_tabs_leading_back_into_leads(client):
    html = client.get("/me").get_data(as_text=True)
    for view in ("active", "closed", "add", "status"):
        assert f'href="/#{view}"' in html
    assert 'href="/me" aria-current="page"' in html and "page-app" in html


def test_leads_page_tabs_still_switch_in_place(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="#active"' in html and 'href="/#active"' not in html


def test_hub_shows_the_due_count_on_the_active_tab(app, client, user):
    from app.models import Lead
    with app.app_context():
        db.session.add(Lead(company="Due Co", owner_code=user.code, stage="New enquiry", follow_up_date=today_local()))
        db.session.commit()
    assert '<b class="nav-badge">1</b>' in client.get("/me").get_data(as_text=True)


def test_no_bottom_tabs_without_leads(app, manager_client):
    html = manager_client.get("/me").get_data(as_text=True)          # project managers have no Leads service
    assert 'class="bottom-nav"' not in html and "page-plain" in html

"""All clients / All projects: the admin-only, company-wide views under Manage, as opposed to the
ordinary Clients and Projects services each person sees scoped to their own work."""

from app.extensions import db
from app.models import Client, Project


def make_client_in(name, district, city):
    c = Client(name=name, district=district, city=city)
    db.session.add(c)
    db.session.commit()
    return c


# ---------- admin only ----------

def test_all_clients_and_all_projects_are_admin_only(client, manager_client, accounts_client, admin_client):
    for who in (client, manager_client, accounts_client):
        assert who.get("/all-clients").status_code == 403
        assert who.get("/all-projects").status_code == 403
    assert admin_client.get("/all-clients").status_code == 200
    assert admin_client.get("/all-projects").status_code == 200


def test_all_clients_needs_sign_in(anon):
    assert anon.get("/all-clients").status_code == 302
    assert anon.get("/all-projects").status_code == 302


def test_pages_are_titled_and_not_part_of_leads(admin_client):
    html = admin_client.get("/all-clients").get_data(as_text=True)
    assert "all_clients.js" in html
    assert '<span class="brand-mark" aria-hidden="true"></span>All clients</a>' in html
    assert "app.js" not in html and "bottom-nav" not in html

    html = admin_client.get("/all-projects").get_data(as_text=True)
    assert "all_projects.js" in html
    assert '<span class="brand-mark" aria-hidden="true"></span>All projects</a>' in html


def test_the_links_are_only_in_the_admin_menu(client, admin_client):
    html = client.get("/").get_data(as_text=True)
    assert "All clients" not in html and "All projects" not in html
    html = admin_client.get("/").get_data(as_text=True)
    assert "All clients" in html and "All projects" in html


# ---------- these pages reuse the ordinary APIs, which already give the admin everything ----------

def test_admin_sees_every_client_regardless_of_owner(app, admin_client, manager_client):
    with app.app_context():
        make_client_in("Sunrise Hospital", "Nagpur", "Nagpur")
    assert len(admin_client.get("/api/clients").get_json()["clients"]) == 1
    assert manager_client.get("/api/clients").get_json()["clients"] == []        # not theirs, so not visible to them

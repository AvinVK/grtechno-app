"""Giving a client their own login (kohal, 2026-10-22: "clients should be able to login. a new role
called client but along with that the admin would also have to choose which client it is") - see
app/clients.py's give_login, and tests/test_client_portal.py for what that login can then actually see."""

from app.extensions import db
from app.models import Client, User


def make_client(name="Kalyani Cold Storage", contact_name="Mr. Kalyani"):
    c = Client(name=name, contact_name=contact_name)
    db.session.add(c)
    db.session.commit()
    return c.id


def test_only_the_admin_can_give_login_access(client, accounts_client, admin_client):
    cid = make_client()
    for who in (client, accounts_client):
        assert who.post(f"/api/clients/{cid}/login").status_code == 403
    assert admin_client.post(f"/api/clients/{cid}/login").status_code == 201


def test_giving_login_access_creates_a_client_role_user(app, admin_client):
    cid = make_client(contact_name="Mr. Kalyani")
    res = admin_client.post(f"/api/clients/{cid}/login")
    assert res.status_code == 201
    body = res.get_json()
    assert body["setup_code"] and body["code_days"]
    with app.app_context():
        user = db.session.get(User, body["user"]["code"])
        assert user.role_key == "client" and user.client_id == cid
        assert user.name == "Mr. Kalyani"


def test_giving_login_access_twice_reissues_the_same_login_not_a_duplicate(app, admin_client):
    cid = make_client()
    first = admin_client.post(f"/api/clients/{cid}/login").get_json()
    second = admin_client.post(f"/api/clients/{cid}/login").get_json()
    assert first["user"]["code"] == second["user"]["code"]
    assert first["setup_code"] != second["setup_code"]
    with app.app_context():
        assert User.query.filter_by(client_id=cid).count() == 1


def test_client_detail_shows_login_status(app, admin_client):
    cid = make_client()
    before = admin_client.get(f"/api/clients/{cid}").get_json()
    assert before["login"] is None

    admin_client.post(f"/api/clients/{cid}/login")
    after = admin_client.get(f"/api/clients/{cid}").get_json()
    assert after["login"]["status"] == "pending"   # setup code issued, PIN not set yet


def test_a_client_with_no_contact_name_falls_back_to_the_client_name(admin_client):
    cid = make_client("Standalone Site", contact_name="")
    res = admin_client.post(f"/api/clients/{cid}/login")
    assert res.status_code == 201 and res.get_json()["user"]["name"] == "Standalone Site"


# ---------- the Clients list flags who already has a login, without a tap into each one ----------

def test_the_clients_list_flags_which_clients_already_have_a_login(admin_client):
    with_login = make_client("Kailash Hospital")
    without_login = make_client("Orchid Heights CHS")
    admin_client.post(f"/api/clients/{with_login}/login")

    clients = {c["id"]: c for c in admin_client.get("/api/clients").get_json()["clients"]}
    assert clients[with_login]["has_login"] is True
    assert clients[without_login]["has_login"] is False

"""Giving a client their own login (kohal, 2026-10-22: "clients should be able to login. a new role
called client but along with that the admin would also have to choose which client it is") - see
app/clients.py's give_login, and tests/test_client_portal.py for what that login can then actually see."""

from app.extensions import db
from app.models import Client, User


def make_client(name="Kalyani Cold Storage", contact_name="Mr. Kalyani", phone="9876543210"):
    c = Client(name=name, contact_name=contact_name, phone=phone)
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


# ---------- the login id is the client's own phone number, not a generated name-code ----------
# (kohal, 2026-10-23: "the login of client should be mapped to its mobile number... no client will be
# patient enough to enter the code and set the pin. so number will be the mapping key")

def test_the_client_logs_in_with_their_own_phone_number(admin_client):
    cid = make_client(phone="9876543210")
    res = admin_client.post(f"/api/clients/{cid}/login")
    assert res.status_code == 201 and res.get_json()["user"]["userid"] == "9876543210"


def test_a_formatted_phone_number_is_normalised_to_just_the_digits(admin_client):
    cid = make_client(phone="+91 98765-43210")
    res = admin_client.post(f"/api/clients/{cid}/login")
    assert res.status_code == 201 and res.get_json()["user"]["userid"] == "9876543210"


def test_giving_login_access_is_refused_without_a_valid_phone_number(admin_client):
    no_phone = make_client("No Phone Client", phone="")
    too_short = make_client("Short Phone Client", phone="12345")
    for cid in (no_phone, too_short):
        res = admin_client.post(f"/api/clients/{cid}/login")
        assert res.status_code == 422 and "phone" in res.get_json()["error"].lower()


def test_two_clients_cannot_share_the_same_phone_login(admin_client):
    first = make_client("First Client", phone="9876543210")
    second = make_client("Second Client", phone="9876543210")
    assert admin_client.post(f"/api/clients/{first}/login").status_code == 201
    blocked = admin_client.post(f"/api/clients/{second}/login")
    assert blocked.status_code == 422


# ---------- the Clients list flags who has actually logged in, without a tap into each one ----------

def test_the_clients_list_flags_who_has_actually_logged_in(app, admin_client):
    """kohal, 2026-10-22: "change login to 'has logged in'" - a setup code sitting unused shouldn't count,
    only a client who has actually set their PIN."""
    logged_in = make_client("Kailash Hospital", phone="9876543210")
    still_pending = make_client("Standalone Site", phone="9876543211")
    not_given = make_client("Orchid Heights CHS", phone="9876543212")
    code = admin_client.post(f"/api/clients/{logged_in}/login").get_json()["user"]["code"]
    admin_client.post(f"/api/clients/{still_pending}/login")
    with app.app_context():
        from werkzeug.security import generate_password_hash
        user = db.session.get(User, code)
        user.password_hash = generate_password_hash("482917")
        db.session.commit()

    clients = {c["id"]: c for c in admin_client.get("/api/clients").get_json()["clients"]}
    assert clients[logged_in]["has_logged_in"] is True
    assert clients[still_pending]["has_logged_in"] is False
    assert clients[not_given]["has_logged_in"] is False

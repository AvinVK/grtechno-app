from app.extensions import db
from app.models import Lead, Module, User
from conftest import make_user, signed_in


def new_lead(client, **fields):
    res = client.post("/api/leads", json={"company": "Acme", **fields})
    assert res.status_code == 201, res.get_json()
    return res.get_json()


# ---------- the Users screen API is admin only ----------

def test_only_the_admin_can_manage_users(client, admin_client, user):
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json={"name": "Sneaky"}).status_code == 403
    assert client.post(f"/api/users/{user.code}/reset", json={}).status_code == 403
    assert admin_client.get("/api/users").status_code == 200


def test_admin_adds_a_user_and_sees_the_setup_code_once(admin_client, app):
    res = admin_client.post("/api/users", json={"name": "Asha Rao"})
    body = res.get_json()
    assert res.status_code == 201
    assert body["user"]["userid"].startswith("asharao-") and body["user"]["status"] == "pending"
    assert len(body["setup_code"].replace("-", "")) == 8
    listing = admin_client.get("/api/users").get_json()["users"]
    assert any(u["userid"] == body["user"]["userid"] for u in listing)
    assert "setup_code" not in str(listing)
    assert admin_client.post("/api/users", json={"name": "  ??  "}).status_code == 422


def test_admin_account_is_protected(admin_client, admin):
    assert admin_client.post(f"/api/users/{admin.code}/reset", json={}).status_code == 400
    assert admin_client.post(f"/api/users/{admin.code}/active", json={"active": False}).status_code == 400
    assert db.session.get(User, admin.code).is_active


# ---------- people only see their own leads ----------

def test_users_only_see_and_touch_their_own_leads(app, client, user):
    mine = new_lead(client, company="Mine")
    other_user = make_user("Other")
    other = signed_in(app, other_user)
    theirs = new_lead(other, company="Theirs")

    assert [l["company"] for l in client.get("/api/state").get_json()["leads"]] == ["Mine"]
    assert client.get(f"/api/leads/{theirs['id']}").status_code == 404
    assert client.patch(f"/api/leads/{theirs['id']}", json={"company": "Hacked"}).status_code == 404
    assert client.delete(f"/api/leads/{theirs['id']}").status_code == 404
    assert client.post(f"/api/leads/{theirs['id']}/notes", json={"text": "hi"}).status_code == 404
    assert other.get(f"/api/leads/{mine['id']}").status_code == 404
    assert db.session.get(Lead, theirs["id"]).company == "Theirs"

    csv_text = client.get("/export.csv").get_data(as_text=True)
    assert "Mine" in csv_text and "Theirs" not in csv_text


def test_summary_counts_only_own_leads(app, client):
    new_lead(client, est_value=100)
    signed_in(app, make_user("Other")).post("/api/leads", json={"company": "X", "est_value": 5000})
    summary = client.get("/api/state").get_json()["summary"]
    assert summary["open_count"] == 1 and summary["open_value"] == 100


def test_new_leads_belong_to_whoever_added_them(client, user):
    lead = new_lead(client)
    assert lead["owner_name"] == "Tester"
    assert db.session.get(Lead, lead["id"]).owner_code == user.code


def test_admin_sees_every_lead_with_its_owner(app, client, admin_client):
    new_lead(client, company="Tester lead")
    new_lead(admin_client, company="Admin lead")
    leads = admin_client.get("/api/state").get_json()["leads"]
    assert {(l["company"], l["owner_name"]) for l in leads} == {("Tester lead", "Tester"), ("Admin lead", "grtechno")}
    assert admin_client.get("/api/state").get_json()["me"]["is_admin"] is True
    assert len(client.get("/api/state").get_json()["leads"]) == 1


# ---------- command line ----------

def test_create_admin_command(app):
    runner = app.test_cli_runner()
    first = runner.invoke(args=["create-admin"])
    assert first.exit_code == 0 and "grtechno-" in first.output and "Setup code" in first.output
    admin = User.query.filter_by(is_admin=True).one()
    assert admin.name == "grtechno" and admin.status == "pending"

    second = runner.invoke(args=["create-admin"])                              # only one admin
    assert second.exit_code != 0 and "already exists" in second.output

    reset = runner.invoke(args=["reset-pin", admin.userid])
    assert reset.exit_code == 0 and "New setup code" in reset.output
    assert runner.invoke(args=["reset-pin", "ghost-0000"]).exit_code != 0


def test_admin_can_be_created_with_a_chosen_code(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["create-admin", "--code", "12"]).exit_code != 0
    assert runner.invoke(args=["create-admin", "--code", "0123"]).exit_code != 0
    ok = runner.invoke(args=["create-admin", "--code", "3766"])
    assert ok.exit_code == 0 and "grtechno-3766" in ok.output
    admin = db.session.get(User, "3766")
    assert admin.userid == "grtechno-3766" and admin.is_admin


def test_chosen_code_must_be_free(app):
    from app.auth import create_user
    create_user("Taken", code="4321")
    db.session.commit()
    try:
        create_user("Other", code="4321")
    except ValueError as err:
        assert "already used" in str(err)
    else:
        raise AssertionError("expected ValueError")


# ---------- the Users page is its own page, not part of Leads ----------

def test_users_page_is_admin_only_and_titled_users(admin_client, client, anon):
    page = admin_client.get("/users")
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and "users.js" in html
    assert '<span class="brand-mark" aria-hidden="true"></span>Users &amp; roles</a>' in html      # top bar names the page, not Leads
    assert 'href="/users" aria-current="page"' in html                                  # marked in the menu
    assert "app.js" not in html and "bottom-nav" not in html                            # none of the Leads screen
    assert client.get("/users").status_code == 403
    assert anon.get("/users").status_code == 302


def test_users_page_does_not_need_the_lead_desk_service(admin_client):
    Module.query.filter_by(key="leads").update({"is_active": False})                   # even with Leads switched off
    db.session.commit()
    assert admin_client.get("/users").status_code == 200
    assert admin_client.get("/api/users").status_code == 200

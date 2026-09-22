from datetime import date, timedelta

from app.extensions import db
from app.models import Attendance, Client, Project, utcnow


def make_project(title="Sprinkler install"):
    client = Client(name="Sunrise Hospital")
    db.session.add(client)
    db.session.flush()
    project = Project(client=client, title=title, status="running")
    db.session.add(project)
    db.session.commit()
    return project


# ---------- everyone can open it ----------

def test_every_role_can_open_attendance(client, manager_client, accounts_client, admin_client):
    for who in (client, manager_client, accounts_client, admin_client):
        assert who.get("/attendance").status_code == 200
        assert who.get("/api/attendance/state").status_code == 200


def test_needs_sign_in(anon):
    assert anon.get("/api/attendance/state").status_code == 401
    assert anon.get("/attendance").status_code == 302


# ---------- checking in and out ----------

def test_check_in_with_no_project_then_check_out(client):
    state = client.get("/api/attendance/state").get_json()
    assert state["today"] is None and state["can_see_team"] is False

    res = client.post("/api/attendance/check-in", json={})
    assert res.status_code == 201
    today = res.get_json()["today"]
    assert today["project_id"] is None and today["check_out_at"] is None and today["hours"] is None

    out = client.post("/api/attendance/check-out")
    assert out.status_code == 200
    assert out.get_json()["today"]["check_out_at"] is not None
    assert out.get_json()["today"]["hours"] is not None


def test_check_in_against_a_project(client, app):
    with app.app_context():
        project = make_project()
        project_id = project.id
    res = client.post("/api/attendance/check-in", json={"project_id": project_id})
    body = res.get_json()["today"]
    assert body["project_id"] == project_id and body["project_title"] == "Sprinkler install"


def test_check_in_with_a_bad_project_id_is_rejected(client):
    res = client.post("/api/attendance/check-in", json={"project_id": 999999})
    assert res.status_code == 422 and "project_id" in res.get_json()["fields"]


def test_only_one_check_in_per_day(client):
    assert client.post("/api/attendance/check-in", json={}).status_code == 201
    again = client.post("/api/attendance/check-in", json={})
    assert again.status_code == 409


def test_cannot_check_out_without_checking_in(client):
    assert client.post("/api/attendance/check-out").status_code == 409


def test_cannot_check_out_twice(client):
    client.post("/api/attendance/check-in", json={})
    assert client.post("/api/attendance/check-out").status_code == 200
    assert client.post("/api/attendance/check-out").status_code == 409


def test_history_shows_past_days(client, app, user):
    with app.app_context():
        db.session.add(Attendance(
            user_code=user.code, work_date=date.today() - timedelta(days=1), check_in_at=utcnow(),
        ))
        db.session.commit()
    state = client.get("/api/attendance/state").get_json()
    assert len(state["history"]) == 1
    assert state["history"][0]["work_date"] == (date.today() - timedelta(days=1)).isoformat()


# ---------- who sees whose attendance ----------

def test_only_sees_all_roles_can_open_the_team_register(client, accounts_client, admin_client):
    client.post("/api/attendance/check-in", json={})
    assert client.get("/api/attendance/team").status_code == 403
    assert accounts_client.get("/api/attendance/team").status_code == 200
    assert admin_client.get("/api/attendance/team").status_code == 200


def test_team_register_shows_everyones_checkins_for_the_day(client, manager_client, admin_client):
    client.post("/api/attendance/check-in", json={})
    manager_client.post("/api/attendance/check-in", json={})
    body = admin_client.get("/api/attendance/team").get_json()
    names = {r["user_name"] for r in body["records"]}
    assert {"Tester", "Priya Manager"} <= names


def test_team_register_can_be_filtered_by_date(client, admin_client):
    client.post("/api/attendance/check-in", json={})
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    empty = admin_client.get(f"/api/attendance/team?date={yesterday}").get_json()
    assert empty["records"] == []
    today = admin_client.get(f"/api/attendance/team?date={date.today().isoformat()}").get_json()
    assert len(today["records"]) == 1


def test_a_users_state_only_shows_their_own_history(client, manager_client):
    client.post("/api/attendance/check-in", json={})
    manager_client.post("/api/attendance/check-in", json={})
    state = client.get("/api/attendance/state").get_json()
    assert state["today"]["user_code"] not in (None,)  # sanity: a record is theirs
    assert all(h["user_name"] == "Tester" for h in state["history"])

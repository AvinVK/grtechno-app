"""Announcements: a message from the admin to a chosen set of employees (kohal, 2026-10-19), with a popup
on every page until dismissed - see app/workplan.py (admin side) and app/me.py (the recipient's own side,
deliberately not gated by the workplan module since a recipient might not have Workplan access at all)."""

from app.extensions import db
from app.models import Worker
from conftest import make_user, signed_in


def worker_with_login(app, name="Rafiq Welder"):
    user = make_user(name)
    with app.app_context():
        worker = Worker(name=name, category="manpower", user_code=user.code)
        db.session.add(worker)
        db.session.commit()
        return worker.id, user


def worker_without_login(name="No Login Nikhil"):
    worker = Worker(name=name, category="manpower")
    db.session.add(worker)
    db.session.commit()
    return worker.id


# ---------- sending ----------

def test_only_the_admin_can_send_one(app, manager_client, admin_client):
    wid, _ = worker_with_login(app)
    refused = manager_client.post("/api/announcements", json={"message": "hello", "worker_ids": [wid]})
    assert refused.status_code == 403

    res = admin_client.post("/api/announcements", json={"message": "hello team", "worker_ids": [wid]})
    assert res.status_code == 201
    body = res.get_json()["announcement"]
    assert body["message"] == "hello team" and body["recipient_count"] == 1 and body["dismissed_count"] == 0


def test_sending_needs_a_message_and_at_least_one_employee(app, admin_client):
    wid, _ = worker_with_login(app)
    no_message = admin_client.post("/api/announcements", json={"message": "", "worker_ids": [wid]})
    assert no_message.status_code == 422 and "message" in no_message.get_json()["fields"]

    no_employees = admin_client.post("/api/announcements", json={"message": "hi", "worker_ids": []})
    assert no_employees.status_code == 422 and "worker_ids" in no_employees.get_json()["fields"]


def test_someone_with_no_login_cant_be_sent_one_a_popup_has_nothing_to_show_them_on(app, admin_client):
    no_login_id = worker_without_login()
    res = admin_client.post("/api/announcements", json={"message": "hi", "worker_ids": [no_login_id]})
    assert res.status_code == 422 and "worker_ids" in res.get_json()["fields"]


def test_a_mixed_selection_only_creates_recipients_for_the_ones_with_a_login(app, admin_client):
    wid, user = worker_with_login(app)
    no_login_id = worker_without_login()
    res = admin_client.post("/api/announcements", json={"message": "hi", "worker_ids": [wid, no_login_id]})
    assert res.status_code == 201 and res.get_json()["announcement"]["recipient_count"] == 1

    worker_client = signed_in(app, user)
    assert len(worker_client.get("/api/me/announcements").get_json()["announcements"]) == 1


# ---------- the recipient's own side ----------

def test_a_recipient_sees_it_and_can_dismiss_it(app, admin_client):
    wid, user = worker_with_login(app, "Sunny Welder")
    sent = admin_client.post("/api/announcements", json={"message": "Diwali holiday notice", "worker_ids": [wid]}).get_json()["announcement"]

    worker_client = signed_in(app, user)
    seen = worker_client.get("/api/me/announcements").get_json()["announcements"]
    assert len(seen) == 1
    assert seen[0]["message"] == "Diwali holiday notice" and seen[0]["created_by_name"] == "grtechno"
    recipient_id = seen[0]["recipient_id"]

    dismiss = worker_client.post(f"/api/me/announcements/{recipient_id}/dismiss")
    assert dismiss.status_code == 204
    assert worker_client.get("/api/me/announcements").get_json()["announcements"] == []

    # The admin's own history now shows it as seen.
    history = admin_client.get("/api/announcements").get_json()["announcements"]
    assert next(a for a in history if a["id"] == sent["id"])["dismissed_count"] == 1


def test_someone_elses_announcement_doesnt_show_up_and_cant_be_dismissed_by_the_wrong_person(app, admin_client):
    wid, user = worker_with_login(app, "Sunny Welder")
    other_wid, other_user = worker_with_login(app, "Rafiq Fitter")
    admin_client.post("/api/announcements", json={"message": "just for Sunny", "worker_ids": [wid]})

    other_client = signed_in(app, other_user)
    assert other_client.get("/api/me/announcements").get_json()["announcements"] == []

    worker_client = signed_in(app, user)
    recipient_id = worker_client.get("/api/me/announcements").get_json()["announcements"][0]["recipient_id"]
    assert other_client.post(f"/api/me/announcements/{recipient_id}/dismiss").status_code == 404


def test_more_than_one_waiting_comes_back_oldest_first(app, admin_client):
    wid, user = worker_with_login(app)
    admin_client.post("/api/announcements", json={"message": "first", "worker_ids": [wid]})
    admin_client.post("/api/announcements", json={"message": "second", "worker_ids": [wid]})

    worker_client = signed_in(app, user)
    seen = worker_client.get("/api/me/announcements").get_json()["announcements"]
    assert [a["message"] for a in seen] == ["first", "second"]


# ---------- history ----------

def test_only_the_admin_can_see_the_history(app, manager_client, admin_client):
    wid, _ = worker_with_login(app)
    admin_client.post("/api/announcements", json={"message": "hi", "worker_ids": [wid]})
    assert manager_client.get("/api/announcements").status_code == 403
    assert len(admin_client.get("/api/announcements").get_json()["announcements"]) == 1

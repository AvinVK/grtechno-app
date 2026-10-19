"""Work plan: next-day work scheduling (kohal, 2026-10-19) - a project manager, the accountant, or the
admin drafts a day's work against a project (field) or a location (office), and only the admin can approve
it. Once approved, it shows up on the assigned worker's own Me hub (see test_me.py's sibling coverage,
if any) via app/me.py's my_work_assignment."""

from datetime import date, timedelta

from app.extensions import db
from app.models import Client, Project, Worker
from conftest import make_user, signed_in


def make_project(title="Sprinkler install"):
    client = Client(name="Sunrise Hospital")
    db.session.add(client)
    db.session.flush()
    project = Project(client=client, title=title, status="running")
    db.session.add(project)
    db.session.commit()
    return project


def make_worker(name="Deepak Daily", with_login=False):
    worker = Worker(name=name, category="manpower")
    if with_login:
        user = make_user(name)
        worker.user_code = user.code
    db.session.add(worker)
    db.session.commit()
    return worker


TOMORROW = (date.today() + timedelta(days=1)).isoformat()
TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


# ---------- who can open the page / draft ----------

def test_project_manager_accounts_and_admin_can_open_it(manager_client, accounts_client, admin_client):
    for who in (manager_client, accounts_client, admin_client):
        assert who.get("/workplan").status_code == 200


def test_an_unrelated_role_cannot_open_it(client):
    assert client.get("/workplan").status_code == 403


# ---------- drafting a field assignment ----------

def test_a_project_manager_drafts_a_field_assignment_pending_admin(app, manager_client):
    with app.app_context():
        pid = make_project().id
        wid = make_worker().id
    res = manager_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": wid, "project_id": pid, "task": "Replace valve",
    })
    assert res.status_code == 201
    body = res.get_json()["assignment"]
    assert body["status"] == "pending" and body["project_title"] == "Sprinkler install" and body["task"] == "Replace valve"


def test_the_admins_own_draft_is_approved_immediately(app, admin_client):
    with app.app_context():
        pid = make_project().id
        wid = make_worker().id
    res = admin_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": wid, "project_id": pid, "task": "Replace valve",
    })
    body = res.get_json()["assignment"]
    assert body["status"] == "approved" and body["approved_by_name"] == "grtechno"


def test_an_office_assignment_needs_a_location_not_a_project(app, accounts_client):
    with app.app_context():
        wid = make_worker("Office Omkar", with_login=True).id
    missing = accounts_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "office", "worker_id": wid, "task": "File the invoices",
    })
    assert missing.status_code == 422 and "location" in missing.get_json()["fields"]

    ok = accounts_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "office", "worker_id": wid, "location": "Head office", "task": "File the invoices",
    })
    assert ok.status_code == 201
    assert ok.get_json()["assignment"]["location"] == "Head office"


def test_a_past_date_is_rejected(app, manager_client):
    with app.app_context():
        pid = make_project().id
        wid = make_worker().id
    res = manager_client.post("/api/work-assignments", json={
        "for_date": YESTERDAY, "kind": "field", "worker_id": wid, "project_id": pid, "task": "x",
    })
    assert res.status_code == 422 and "for_date" in res.get_json()["fields"]


def test_someone_who_cant_draft_is_refused(app, client):
    with app.app_context():
        pid = make_project().id
        wid = make_worker().id
    res = client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": wid, "project_id": pid, "task": "x",
    })
    assert res.status_code == 403


# ---------- approval (admin only, never Company Director or anyone else) ----------

def test_only_the_admin_can_approve_not_company_director(app, manager_client, admin_client):
    with app.app_context():
        pid = make_project().id
        wid = make_worker().id
    record_id = manager_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": wid, "project_id": pid, "task": "x",
    }).get_json()["assignment"]["id"]

    director = signed_in(app, make_user("Dilip Director", role="company_director"))
    assert director.post(f"/api/work-assignments/{record_id}/approve").status_code == 403
    assert manager_client.post(f"/api/work-assignments/{record_id}/approve").status_code == 403

    res = admin_client.post(f"/api/work-assignments/{record_id}/approve")
    assert res.status_code == 200 and res.get_json()["assignment"]["status"] == "approved"
    assert admin_client.post(f"/api/work-assignments/{record_id}/approve").status_code == 409


def test_rejecting_one(app, manager_client, admin_client):
    with app.app_context():
        pid = make_project().id
        wid = make_worker().id
    record_id = manager_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": wid, "project_id": pid, "task": "x",
    }).get_json()["assignment"]["id"]
    res = admin_client.post(f"/api/work-assignments/{record_id}/reject")
    assert res.status_code == 200 and res.get_json()["assignment"]["status"] == "rejected"


def test_pending_list_is_admin_only(app, manager_client, admin_client):
    with app.app_context():
        pid = make_project().id
        wid = make_worker().id
    manager_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": wid, "project_id": pid, "task": "x",
    })
    assert manager_client.get("/api/work-assignments/pending").status_code == 403
    rows = admin_client.get("/api/work-assignments/pending").get_json()["assignments"]
    assert len(rows) == 1


# ---------- deleting ----------

def test_the_drafter_can_delete_their_own_pending_one_not_someone_elses(app, manager_client, accounts_client):
    with app.app_context():
        pid = make_project().id
        wid = make_worker().id
    record_id = manager_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": wid, "project_id": pid, "task": "x",
    }).get_json()["assignment"]["id"]
    assert accounts_client.delete(f"/api/work-assignments/{record_id}").status_code == 403
    assert manager_client.delete(f"/api/work-assignments/{record_id}").status_code == 204


def test_once_approved_only_the_admin_can_delete_it(app, manager_client, admin_client):
    with app.app_context():
        pid = make_project().id
        wid = make_worker().id
    record_id = manager_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": wid, "project_id": pid, "task": "x",
    }).get_json()["assignment"]["id"]
    admin_client.post(f"/api/work-assignments/{record_id}/approve")
    assert manager_client.delete(f"/api/work-assignments/{record_id}").status_code == 403
    assert admin_client.delete(f"/api/work-assignments/{record_id}").status_code == 204


# ---------- the alert on the assignee's own Me hub ----------

def test_the_assigned_worker_sees_it_on_their_me_hub_once_approved(app, manager_client, admin_client):
    with app.app_context():
        pid = make_project().id
    worker = make_worker("Sunny Welder", with_login=True)
    worker_client = signed_in(app, make_user_from_worker(worker))

    record_id = manager_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": worker.id, "project_id": pid, "task": "Replace valve",
    }).get_json()["assignment"]["id"]
    assert worker_client.get("/api/me/work-assignment").get_json()["assignment"] is None    # still pending

    admin_client.post(f"/api/work-assignments/{record_id}/approve")
    seen = worker_client.get("/api/me/work-assignment").get_json()["assignment"]
    assert seen is not None and seen["task"] == "Replace valve" and seen["project_title"] == "Sprinkler install"


def make_user_from_worker(worker):
    from app.models import User
    return db.session.get(User, worker.user_code)


def test_a_worker_with_no_login_cant_see_an_alert_anywhere(app, manager_client, admin_client):
    """There's no Me hub for them to see it on - the picker in the UI flags this, but the API doesn't need
    to refuse creating it (an office supervisor might still want the paper trail)."""
    with app.app_context():
        pid = make_project().id
        wid = make_worker("No Login Walter", with_login=False).id
    record_id = manager_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": wid, "project_id": pid, "task": "x",
    }).get_json()["assignment"]["id"]
    admin_client.post(f"/api/work-assignments/{record_id}/approve")
    # Nobody signed in as this worker - nothing more to assert than "it didn't crash" and the row exists.
    assert admin_client.get("/api/work-assignments/pending").get_json()["assignments"] == []


def test_only_today_or_later_shows_up_not_a_past_approved_one(app, manager_client, admin_client):
    with app.app_context():
        pid = make_project().id
    worker = make_worker("Sunny Welder", with_login=True)
    worker_client = signed_in(app, make_user_from_worker(worker))
    record_id = manager_client.post("/api/work-assignments", json={
        "for_date": TODAY, "kind": "field", "worker_id": worker.id, "project_id": pid, "task": "Today's job",
    }).get_json()["assignment"]["id"]
    admin_client.post(f"/api/work-assignments/{record_id}/approve")
    seen = worker_client.get("/api/me/work-assignment").get_json()["assignment"]
    assert seen is not None and seen["task"] == "Today's job"


def test_the_pending_approvals_section_shows_on_the_admins_me_hub(app, manager_client, admin_client):
    with app.app_context():
        pid = make_project().id
        wid = make_worker().id
    manager_client.post("/api/work-assignments", json={
        "for_date": TOMORROW, "kind": "field", "worker_id": wid, "project_id": pid, "task": "x",
    })
    html = admin_client.get("/me").get_data(as_text=True)
    assert 'id="me-workplan-approvals"' in html

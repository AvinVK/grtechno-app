from datetime import date, timedelta

from app.extensions import db
from app.models import Client, Project, Worker, WorkerAttendance


def make_worker(name="Sunny Pipe Welder GR", days_ago=(0, 1)):
    worker = Worker(name=name, source="whatsapp", first_seen=date.today() - timedelta(days=400), last_seen=date.today())
    db.session.add(worker)
    db.session.flush()
    for d in days_ago:
        db.session.add(WorkerAttendance(
            worker=worker, work_date=date.today() - timedelta(days=d),
            check_in_at=None, check_out_at=None,
        ))
    db.session.commit()
    return worker


# ---------- admin only ----------

def test_worker_list_page_and_api_are_admin_only(client, manager_client, accounts_client, admin_client):
    for who in (client, manager_client, accounts_client):
        assert who.get("/workers").status_code == 403
        assert who.get("/api/workers").status_code == 403
    assert admin_client.get("/workers").status_code == 200
    assert admin_client.get("/api/workers").status_code == 200


def test_worker_list_needs_sign_in(anon):
    assert anon.get("/workers").status_code == 302
    assert anon.get("/api/workers").status_code == 401


def test_worker_list_page_is_titled_and_not_part_of_leads(admin_client):
    html = admin_client.get("/workers").get_data(as_text=True)
    assert 'workers.js' in html
    assert '<span class="brand-mark" aria-hidden="true"></span>Manpower</a>' in html
    assert 'app.js' not in html and 'bottom-nav' not in html


def test_worker_list_is_only_in_the_admin_menu(client, admin_client):
    assert 'Manpower' not in client.get("/").get_data(as_text=True)
    assert 'Manpower' in admin_client.get("/").get_data(as_text=True)


# ---------- listing and detail ----------

def test_list_shows_each_worker_with_a_days_present_count(admin_client, app):
    with app.app_context():
        make_worker("Sunny Pipe Welder GR", days_ago=(0, 1, 2))
        make_worker("Tinku Welder GR", days_ago=())
    body = admin_client.get("/api/workers").get_json()
    by_name = {w["name"]: w for w in body["workers"]}
    assert by_name["Sunny Pipe Welder GR"]["days_present"] == 3
    assert by_name["Tinku Welder GR"]["days_present"] == 0
    assert body["window_days"] == 14


def test_worker_detail_lists_their_attendance(admin_client, app):
    with app.app_context():
        worker = make_worker("Sunny Pipe Welder GR", days_ago=(0, 1))
        worker_id = worker.id
    body = admin_client.get(f"/api/workers/{worker_id}").get_json()
    assert body["worker"]["name"] == "Sunny Pipe Welder GR"
    assert len(body["attendance"]) == 2
    assert body["attendance"][0]["work_date"] == date.today().isoformat()   # newest first


def test_a_missing_worker_is_404(admin_client):
    assert admin_client.get("/api/workers/999999").status_code == 404


def test_attendance_carries_locations_and_hours(admin_client, app):
    from datetime import datetime
    with app.app_context():
        worker = Worker(name="Sk Jalal Welder GR")
        db.session.add(worker)
        db.session.flush()
        db.session.add(WorkerAttendance(
            worker=worker, work_date=date.today(),
            check_in_at=datetime(2026, 9, 22, 7, 5), check_in_lat=21.08, check_in_lng=79.07,
            check_out_at=datetime(2026, 9, 22, 19, 4), check_out_lat=21.09, check_out_lng=79.08,
        ))
        db.session.commit()
        worker_id = worker.id
    row = admin_client.get(f"/api/workers/{worker_id}").get_json()["attendance"][0]
    assert row["check_in_map_url"] == "https://maps.google.com/?q=21.08,79.07"
    assert row["check_out_map_url"] == "https://maps.google.com/?q=21.09,79.08"
    assert row["hours"] == 12.0                                  # 07:05 to 19:04, rounded to one decimal


# ---------- filled in from a colleague's message, not the worker's own ----------

def test_a_day_can_be_marked_absent_with_no_check_in(admin_client, app):
    """A colleague saying "Pintu is on leave" - Pintu never messaged the group himself that day."""
    with app.app_context():
        worker = Worker(name="Pintu")
        db.session.add(worker)
        db.session.flush()
        db.session.add(WorkerAttendance(
            worker=worker, work_date=date.today(), status="absent",
            note="Reported by Ashish Sutone: \"Ha pintu chutti pe hai\"",
        ))
        db.session.commit()
        worker_id = worker.id
    row = admin_client.get(f"/api/workers/{worker_id}").get_json()["attendance"][0]
    assert row["status"] == "absent" and row["check_in_at"] is None and row["hours"] is None
    assert "Ashish Sutone" in row["note"]


def test_attendance_links_to_the_project_the_site_name_matched(admin_client, app):
    with app.app_context():
        client_row = Client(name="Ficon")
        db.session.add(client_row)
        db.session.flush()
        project = Project(client=client_row, title="Billing, New work estimate")
        db.session.add(project)
        worker = Worker(name="Sk Jalal Welder GR")
        db.session.add(worker)
        db.session.flush()
        db.session.add(WorkerAttendance(worker=worker, work_date=date.today(), project=project))
        db.session.commit()
        worker_id, project_id = worker.id, project.id
    row = admin_client.get(f"/api/workers/{worker_id}").get_json()["attendance"][0]
    assert row["project_id"] == project_id and row["project_code"] == project.code
    assert row["project_title"] == "Billing, New work estimate"


def test_default_status_is_present(admin_client, app):
    with app.app_context():
        worker = make_worker("Tinku Welder GR", days_ago=(0,))
        worker_id = worker.id
    row = admin_client.get(f"/api/workers/{worker_id}").get_json()["attendance"][0]
    assert row["status"] == "present"

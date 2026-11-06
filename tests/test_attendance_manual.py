"""The admin adds a day of attendance for an employee (kohal, 2026-11-05: "give admin power to add attendance for employees because ...
we are migrating and still using the app parallely")."""

from datetime import timedelta

from app.extensions import db
from app.models import Worker, WorkerAttendance
from app.timeutil import today_local


def _worker(app, name="Ravi Welder", **kw):
    with app.app_context():
        w = Worker(name=name, category="manpower", **kw)
        db.session.add(w)
        db.session.commit()
        return w.id


def _yesterday():
    return (today_local() - timedelta(days=1)).isoformat()


def test_the_admin_adds_a_present_day_with_times(app, admin_client):
    wid = _worker(app)
    day = _yesterday()
    r = admin_client.post("/api/attendance/manual", json={"worker_id": wid, "work_date": day, "check_in": "09:30", "check_out": "18:00", "note": "Site visit"})
    assert r.status_code == 201
    rec = r.get_json()["record"]
    assert rec["worker_name"] == "Ravi Welder" and rec["status"] == "present" and rec["hours"] == 8.5 and rec["note"] == "Site visit"
    with app.app_context():
        row = WorkerAttendance.query.filter_by(worker_id=wid).one()
        assert row.work_date.isoformat() == day
        # a first day for someone with none anchors where they are counted from; it is stored the same way the WhatsApp import stores a day
        assert db.session.get(Worker, wid).first_seen.isoformat() == day


def test_a_day_can_be_added_without_times_or_as_absent(app, admin_client):
    wid = _worker(app)
    d1, d2 = (today_local() - timedelta(days=2)).isoformat(), _yesterday()
    assert admin_client.post("/api/attendance/manual", json={"worker_id": wid, "work_date": d1}).status_code == 201
    r = admin_client.post("/api/attendance/manual", json={"worker_id": wid, "work_date": d2, "status": "absent", "check_in": "09:00"})
    assert r.status_code == 201 and r.get_json()["record"]["status"] == "absent" and r.get_json()["record"]["check_in_at"] is None
    with app.app_context():
        assert {a.work_date.isoformat(): a.status for a in WorkerAttendance.query.filter_by(worker_id=wid)} == {d1: "present", d2: "absent"}


def test_an_existing_day_is_never_overwritten(app, admin_client):
    wid = _worker(app)
    with app.app_context():
        db.session.add(WorkerAttendance(worker_id=wid, work_date=today_local() - timedelta(days=1), status="present", note="from WhatsApp"))
        db.session.commit()
    r = admin_client.post("/api/attendance/manual", json={"worker_id": wid, "work_date": _yesterday(), "status": "absent"})
    assert r.status_code == 409 and "already has attendance" in r.get_json()["error"]
    with app.app_context():
        row = WorkerAttendance.query.filter_by(worker_id=wid).one()
        assert row.status == "present" and row.note == "from WhatsApp"


def test_mistakes_are_caught_before_anything_is_saved(app, admin_client):
    wid = _worker(app)
    tomorrow = (today_local() + timedelta(days=1)).isoformat()
    cases = [
        ({"worker_id": 99999, "work_date": _yesterday()}, "worker_id"),
        ({"worker_id": wid, "work_date": tomorrow}, "work_date"),
        ({"worker_id": wid, "work_date": "not a date"}, "work_date"),
        ({"worker_id": wid, "work_date": _yesterday(), "status": "maybe"}, "status"),
        ({"worker_id": wid, "work_date": _yesterday(), "check_in": "18:00", "check_out": "09:00"}, "check_out"),
        ({"worker_id": wid, "work_date": _yesterday(), "check_out": "18:00"}, "check_in"),
        ({"worker_id": wid, "work_date": _yesterday(), "check_in": "9.30"}, "check_in"),
        ({"worker_id": wid, "work_date": _yesterday(), "project_id": 99999}, "project_id"),
    ]
    for body, field in cases:
        r = admin_client.post("/api/attendance/manual", json=body)
        assert r.status_code == 422 and field in r.get_json()["fields"], body
    with app.app_context():
        assert WorkerAttendance.query.count() == 0


def test_only_the_admin_can_add_a_day(app, client, accounts_client):
    wid = _worker(app)
    body = {"worker_id": wid, "work_date": _yesterday()}
    for c in (client, accounts_client):
        assert c.post("/api/attendance/manual", json=body).status_code in (403, 404)
        assert c.get("/api/attendance/manual/options").status_code in (403, 404)
    with app.app_context():
        assert WorkerAttendance.query.count() == 0


def test_the_team_register_shows_the_recorded_days_and_the_options_list_employees(app, admin_client):
    wid = _worker(app)
    other = _worker(app, "Sita Helper")
    day = _yesterday()
    admin_client.post("/api/attendance/manual", json={"worker_id": wid, "work_date": day, "check_in": "09:00", "check_out": "17:00"})
    admin_client.post("/api/attendance/manual", json={"worker_id": other, "work_date": day, "status": "absent"})
    data = admin_client.get(f"/api/attendance/team?date={day}").get_json()
    assert [(r["worker_name"], r["status"]) for r in data["recorded"]] == [("Ravi Welder", "present"), ("Sita Helper", "absent")]
    assert admin_client.get("/api/attendance/team").get_json()["recorded"] == []         # only asked for with a day
    opts = admin_client.get("/api/attendance/manual/options").get_json()
    assert {"Ravi Welder", "Sita Helper"} <= {w["name"] for w in opts["workers"]} and opts["today"] == today_local().isoformat()


def test_a_manual_day_counts_as_a_present_day_for_the_employee(app, admin_client):
    wid = _worker(app)
    admin_client.post("/api/attendance/manual", json={"worker_id": wid, "work_date": _yesterday(), "check_in": "09:00", "check_out": "17:00"})
    people = admin_client.get("/api/workforce").get_json()
    everyone = [p for k, v in people.items() if isinstance(v, list) for p in v]
    me = next(p for p in everyone if p["id"] == wid)
    assert me["present_days"] == 1


def test_the_page_has_the_add_button_for_the_admin_only(admin_client, client, accounts_client):
    assert 'id="add-attendance"' in admin_client.get("/attendance").data.decode()
    assert 'id="add-attendance"' not in client.get("/attendance").data.decode()
    assert 'id="add-attendance"' not in accounts_client.get("/attendance").data.decode()


def test_the_calendar_is_prefilled_with_the_days_already_recorded(app, admin_client):
    from datetime import date
    wid = _worker(app)
    d1, d2 = today_local() - timedelta(days=1), today_local() - timedelta(days=2)
    admin_client.post("/api/attendance/manual", json={"worker_id": wid, "work_date": d1.isoformat(), "check_in": "07:00", "check_out": "19:00"})
    admin_client.post("/api/attendance/manual", json={"worker_id": wid, "work_date": d2.isoformat(), "status": "absent"})
    month = f"{d1.year}-{d1.month:02d}"
    days = {d["date"]: d["status"] for d in admin_client.get(f"/api/attendance/manual/calendar?worker_id={wid}&month={month}").get_json()["days"]}
    assert days.get(d1.isoformat()) == "present"
    if d2.month == d1.month:
        assert days.get(d2.isoformat()) == "absent"
    other = _worker(app, "Someone Else")
    assert admin_client.get(f"/api/attendance/manual/calendar?worker_id={other}&month={month}").get_json()["days"] == []   # only this employee's own days
    assert admin_client.get(f"/api/attendance/manual/calendar?worker_id={wid}&month=nope").status_code == 422
    assert admin_client.get("/api/attendance/manual/calendar?worker_id=99999&month=2026-11").status_code == 404
    assert date.fromisoformat(d1.isoformat())


def test_the_calendar_counts_an_approved_check_in_on_the_app_as_present(app, admin_client):
    from app.models import Attendance
    from tests.conftest import make_user
    from app.timeutil import from_local
    from datetime import time
    day = today_local() - timedelta(days=1)
    with app.app_context():
        u = make_user("App Person")
        w = Worker(name="App Person", category="manpower", user_code=u.code)
        db.session.add(w)
        db.session.add(Attendance(user_code=u.code, work_date=day, check_in_at=from_local(day, time(9, 0)), status="approved"))
        db.session.add(Attendance(user_code=u.code, work_date=day - timedelta(days=1), check_in_at=from_local(day, time(9, 0)), status="rejected"))
        db.session.commit()
        wid = w.id
    days = admin_client.get(f"/api/attendance/manual/calendar?worker_id={wid}&month={day.year}-{day.month:02d}").get_json()["days"]
    assert [(d["date"], d["status"], d["source"]) for d in days if d["date"] == day.isoformat()] == [(day.isoformat(), "present", "app")]
    assert all(d["date"] != (day - timedelta(days=1)).isoformat() for d in days)             # a rejected check-in is not a present day


def test_only_the_admin_can_read_the_calendar(app, client):
    wid = _worker(app)
    assert client.get(f"/api/attendance/manual/calendar?worker_id={wid}&month=2026-11").status_code in (403, 404)

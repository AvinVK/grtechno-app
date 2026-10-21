"""Wages (kohal, 2026-10-21): a daily-wage/contractor employee's own day-by-day pay log, built on the same
pay-period math Payroll already computes for the admin (see app/payroll.py's _day_rate_periods/_day_by_day
and tests/test_payroll.py, which these helpers mirror) - see app/wages.py's my_wages."""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Worker, WorkerAttendance
from conftest import make_user, signed_in


def current_slot():
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    if today.day <= 15:
        return date(today.year, today.month, 1), date(today.year, today.month, 15)
    return date(today.year, today.month, 16), date(today.year, today.month, last_day)


def prev_slot(start):
    if start.day == 16:
        return date(start.year, start.month, 1), date(start.year, start.month, 15)
    prev_month_last = start - timedelta(days=1)
    return date(prev_month_last.year, prev_month_last.month, 16), prev_month_last


def daily_wage_user(app, name="Deepak Daily", pin="285193", wage_amount=Decimal("500"), first_seen=None, employment_type="daily_wages"):
    user = make_user(name, pin=pin)
    worker = Worker(name=name, category="manpower", employment_type=employment_type, user_code=user.code,
                     wage_amount=wage_amount, first_seen=first_seen or current_slot()[0])
    db.session.add(worker)
    db.session.commit()
    return signed_in(app, user), worker.id


def present(worker_id, *days):
    for d in days:
        db.session.add(WorkerAttendance(worker_id=worker_id, work_date=d, status="present", check_in_lat=21.1, check_in_lng=79.0))
    db.session.commit()


def extend_data_until(to):
    pusher = Worker(name="Data Until Pusher", category="manpower", first_seen=to)
    db.session.add(pusher)
    db.session.flush()
    db.session.add(WorkerAttendance(worker=pusher, work_date=to, status="present", check_in_lat=21.1, check_in_lng=79.0))
    db.session.commit()


def test_wages_me_needs_a_day_rate_worker(client):
    assert client.get("/api/wages/me").status_code == 403


def test_a_contractor_can_use_wages_too(app):
    """kohal, 2026-10-21: wages.py used to be daily_wages only (see its old gate) - a contractor is the
    same day-rate math everywhere else (app/payroll.py's own DAY_RATE_TYPES), so they get this too now."""
    who, _ = daily_wage_user(app, employment_type="contractor")
    assert who.get("/api/wages/me").status_code == 200


def test_current_cycle_reflects_todays_own_slot(app):
    start, end = current_slot()
    with app.app_context():
        who, wid = daily_wage_user(app, wage_amount=Decimal("500"), first_seen=start)
        present(wid, start)
        extend_data_until(min(end, date.today()))
    data = who.get("/api/wages/me").get_json()
    assert data["current"]["period_start"] == start.isoformat()
    assert data["current"]["days"] >= 1 and data["current"]["earned"] >= 500.0


def test_no_completed_cycle_when_there_isnt_one_yet(app):
    start, _ = current_slot()
    with app.app_context():
        who, wid = daily_wage_user(app, first_seen=start)
    data = who.get("/api/wages/me").get_json()
    assert data["completed"] is None


def test_completed_cycle_shows_the_previous_slots_totals(app):
    """kohal, 2026-10-21: "once 15 days are over (the payroll cycle), it should show a flag saying 15 days
    cycle total is this much, u were absent this much"."""
    start, end = current_slot()
    prev_start, prev_end = prev_slot(start)
    with app.app_context():
        who, wid = daily_wage_user(app, wage_amount=Decimal("500"), first_seen=prev_start)
        present(wid, prev_start, prev_start + timedelta(days=1))
        extend_data_until(min(end, date.today()))
    data = who.get("/api/wages/me").get_json()
    completed = data["completed"]
    assert completed is not None
    assert completed["period_start"] == prev_start.isoformat()
    assert completed["earned"] == 500.0 * completed["days"]
    assert completed["absent"] >= 0


def test_days_list_carries_a_running_cumulative_total(app):
    start, end = current_slot()
    day1, day2 = start, start + timedelta(days=1)
    with app.app_context():
        who, wid = daily_wage_user(app, wage_amount=Decimal("500"), first_seen=start)
        present(wid, day1, day2)
        extend_data_until(min(end, date.today()))
    data = who.get("/api/wages/me").get_json()
    rows = {d["date"]: d for d in data["days"]}
    assert rows[day1.isoformat()]["cumulative"] == 500.0
    if day2.isoformat() in rows:
        assert rows[day2.isoformat()]["cumulative"] == 1000.0
    # Every later day's cumulative is at least the one before it - never goes backwards.
    values = [d["cumulative"] for d in data["days"]]
    assert values == sorted(values)


def test_a_day_with_no_attendance_data_yet_is_not_yet_not_absent(app):
    start, end = current_slot()
    with app.app_context():
        who, wid = daily_wage_user(app, wage_amount=Decimal("500"), first_seen=start)
        extend_data_until(start)   # data only reaches the slot's first day, nothing past it
    data = who.get("/api/wages/me").get_json()
    later_days = [d for d in data["days"] if d["date"] > start.isoformat()]
    if later_days:
        assert all(d["not_yet"] for d in later_days)
        assert all(d["cumulative"] == 0.0 for d in later_days)


def test_a_worker_with_no_wage_set_sees_no_current_or_completed(app):
    with app.app_context():
        who, wid = daily_wage_user(app, wage_amount=None)
    data = who.get("/api/wages/me").get_json()
    assert data["daily_rate"] is None
    assert data["current"] is None and data["completed"] is None and data["days"] == []

"""Payroll (kohal, 2026-10-20): every employee with a wage set, and what they've earned so far - computed
from attendance, never typed in (see app/payroll.py's own docstring for the exact rules). A daily-wage or
contractor employee gets two rows, one per the *current* month's own pay-period slot (1st-15th, 16th-end) -
dates below are built from date.today() itself (via current_slot()/complete_slot(), test-only helpers, not
the thing being tested) rather than hardcoded, since the slots are always relative to whenever the suite
actually runs."""

import calendar
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Worker, WorkerAttendance, WorkerPayment


def current_slot():
    """(start, end) of whichever pay-period slot today falls in - test infrastructure for building fixture
    dates, not a copy of the app's own logic (app/payroll.py's _current_month_slots is what's under test).
    `end` is the slot's own nominal last day (the 15th, or the month's last day) - it can be in the future
    relative to today when today is in the first half; the days/earned math itself never looks past today
    though (can't count a day that hasn't happened yet), so a day-counting precision test should use
    complete_slot() below instead, not this one, to avoid that truncation entirely."""
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    if today.day <= 15:
        return date(today.year, today.month, 1), date(today.year, today.month, 15)
    return date(today.year, today.month, 16), date(today.year, today.month, last_day)


def complete_slot():
    """The current month's first-half slot (1st-15th) - guaranteed not to be truncated by 'today', since
    it's only ever used once we're past it. Needs today.day > 15 to make sense at all (the second half
    hasn't even started yet before that, so there's no complete slot in the current month to test against
    either way) - callers skip rather than fail on a day this doesn't hold, same reasoning Payroll itself
    has no complete slot to show someone a precise day-count for that early in the month."""
    if date.today().day <= 15:
        pytest.skip("needs today to be past the 15th - see this helper's own docstring")
    today = date.today()
    return date(today.year, today.month, 1), date(today.year, today.month, 15)


def a_sunday_in(start, end):
    d = start + timedelta(days=(6 - start.weekday()) % 7)
    assert d <= end, "range too short to contain a Sunday - shouldn't happen, a complete slot is 15-16 days"
    return d


def a_weekday_in(start, end):
    d = start
    while d.weekday() == 6:
        d += timedelta(days=1)
    assert d <= end
    return d


def daily_wage_worker(name="Deepak Daily", wage_amount=Decimal("500"), first_seen=None, employment_type="daily_wages"):
    worker = Worker(name=name, category="manpower", employment_type=employment_type,
                     wage_amount=wage_amount, first_seen=first_seen or current_slot()[0])
    db.session.add(worker)
    db.session.commit()
    return worker


def salaried_worker(name="Sunny Salaried", wage_amount=Decimal("30000"), first_seen=None):
    worker = Worker(name=name, category="staff", employment_type="regular",
                     wage_amount=wage_amount, first_seen=first_seen or date.today().replace(day=1))
    db.session.add(worker)
    db.session.commit()
    return worker


def present(worker, *days):
    for d in days:
        db.session.add(WorkerAttendance(worker=worker, work_date=d, check_in_lat=21.1, check_in_lng=79.0))
    db.session.commit()


def extend_data_until(to):
    """_period()'s own data_until is the latest day ANY attendance exists for, globally - a test whose
    fixture data doesn't reach that far on its own needs a throwaway day to push it there, or the slot's
    own later dates (a Sunday past the test's last real row, say) get truncated out before they're even
    considered. A separate, otherwise-irrelevant worker, so it never shows up in the rows being asserted on."""
    pusher = Worker(name="Data Until Pusher", category="manpower", first_seen=to)
    db.session.add(pusher)
    db.session.flush()
    db.session.add(WorkerAttendance(worker=pusher, work_date=to, check_in_lat=21.1, check_in_lng=79.0))
    db.session.commit()


def months_ago(n):
    """n calendar months back from today, as the 1st of that month - avoids needing dateutil."""
    today = date.today()
    y, m = today.year, today.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def rows_for(data, worker_id):
    return [e for e in data["employees"] if e["id"] == worker_id]


# ---------- module gating ----------

def test_payroll_needs_the_workforce_module(client, accounts_client):
    assert client.get("/payroll").status_code == 403
    assert client.get("/api/payroll/overview").status_code == 403
    assert accounts_client.get("/payroll").status_code == 200
    assert accounts_client.get("/api/payroll/overview").status_code == 200


# ---------- daily wages / contractor: two rows, one per this month's own slot ----------

def test_a_daily_wage_worker_gets_exactly_two_rows_this_month(app, admin_client):
    with app.app_context():
        w = daily_wage_worker()
        wid = w.id
    rows = rows_for(admin_client.get("/api/payroll/overview").get_json(), wid)
    assert len(rows) == 2
    assert [r["period_start"] for r in rows] == sorted(r["period_start"] for r in rows)   # 1-15 slot first
    assert all(r["employment_type"] == "daily_wages" and r["months"] is None for r in rows)


def test_earned_is_present_days_plus_uncredited_sundays_within_the_slot(app, admin_client):
    start, end = complete_slot()
    sunday = a_sunday_in(start, end)
    other_sunday_candidates = [start + timedelta(days=i) for i in range((end - start).days + 1)
                               if (start + timedelta(days=i)).weekday() == 6 and start + timedelta(days=i) != sunday]
    worked_day = a_weekday_in(start, end)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        # Present on an ordinary weekday, and on one of the slot's Sundays (worked that Sunday) - the
        # other Sunday in the slot (if there are two) is left alone to be credited.
        present_days = [worked_day, sunday]
        present(w, *present_days)
        extend_data_until(end)
        wid = w.id
    row = next(r for r in rows_for(admin_client.get("/api/payroll/overview").get_json(), wid) if r["period_start"] == start.isoformat())
    expected_days = len(set(present_days)) + len(other_sunday_candidates)   # the worked Sunday isn't double-credited
    assert row["days"] == expected_days
    assert row["earned"] == 500.0 * expected_days


def test_a_worked_sunday_is_not_paid_twice(app, admin_client):
    start, end = complete_slot()
    sunday = a_sunday_in(start, end)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        present(w, sunday)   # the only present day is itself a Sunday
        extend_data_until(end)
        wid = w.id
    row = next(r for r in rows_for(admin_client.get("/api/payroll/overview").get_json(), wid) if r["period_start"] == start.isoformat())
    # However many Sundays the slot has, the worked one counts once (as present), every other one is
    # credited - never (worked + credited) for the same day.
    sundays_in_slot = sum(1 for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() == 6)
    assert row["days"] == sundays_in_slot
    assert row["earned"] == 500.0 * sundays_in_slot


def test_days_before_first_seen_are_not_credited(app, admin_client):
    start, end = complete_slot()
    sunday = a_sunday_in(start, end)
    # Started the day after the slot's first Sunday - that Sunday must not be credited to them.
    joined = sunday + timedelta(days=1)
    if joined > end:
        joined = sunday   # (slot too short for this scenario - fall back to starting on the Sunday itself)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=joined)
        extend_data_until(end)
        wid = w.id
    row = next(r for r in rows_for(admin_client.get("/api/payroll/overview").get_json(), wid) if r["period_start"] == start.isoformat())
    sundays_after_joining = sum(
        1 for i in range((end - joined).days + 1) if (joined + timedelta(days=i)).weekday() == 6)
    assert row["days"] == sundays_after_joining


def test_contractor_uses_the_same_day_rate_math_as_daily_wages(app, admin_client):
    start, end = complete_slot()
    worked_day = a_weekday_in(start, end)
    with app.app_context():
        w = daily_wage_worker(name="Clive Contractor", wage_amount=Decimal("700"), first_seen=start, employment_type="contractor")
        present(w, worked_day)
        extend_data_until(end)
        wid = w.id
    row = next(r for r in rows_for(admin_client.get("/api/payroll/overview").get_json(), wid) if r["period_start"] == start.isoformat())
    assert row["employment_type"] == "contractor"
    sundays_in_slot = sum(1 for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() == 6)
    assert row["days"] == 1 + sundays_in_slot
    assert row["earned"] == 700.0 * (1 + sundays_in_slot)


# ---------- salary: one flat monthly row, unsplit ----------

def test_salary_is_flat_times_months_elapsed_not_attendance_linked(app, admin_client):
    with app.app_context():
        w = salaried_worker(wage_amount=Decimal("30000"), first_seen=months_ago(2))
        wid = w.id
    rows = rows_for(admin_client.get("/api/payroll/overview").get_json(), wid)
    assert len(rows) == 1
    row = rows[0]
    assert row["months"] == 3
    assert row["earned"] == 90000.0
    assert row["days"] is None and row["period_start"] is None


def test_salary_counts_the_current_partial_month_in_full(app, admin_client):
    with app.app_context():
        w = salaried_worker(wage_amount=Decimal("30000"), first_seen=date.today().replace(day=1))
        wid = w.id
    row = rows_for(admin_client.get("/api/payroll/overview").get_json(), wid)[0]
    assert row["months"] == 1
    assert row["earned"] == 30000.0


# ---------- who shows up at all ----------

def test_an_employee_with_no_wage_set_is_excluded(app, admin_client):
    with app.app_context():
        w = Worker(name="No Wage Nilesh", category="manpower", employment_type="daily_wages")
        db.session.add(w)
        db.session.commit()
        wid = w.id
    assert rows_for(admin_client.get("/api/payroll/overview").get_json(), wid) == []


def test_an_employee_with_no_employment_type_is_excluded(app, admin_client):
    with app.app_context():
        w = Worker(name="Unset Umesh", category="manpower", wage_amount=Decimal("500"))
        db.session.add(w)
        db.session.commit()
        wid = w.id
    assert rows_for(admin_client.get("/api/payroll/overview").get_json(), wid) == []


# ---------- paid / outstanding, matched to a payment's own period_start tag ----------

def test_outstanding_is_earned_minus_a_payment_tagged_to_the_same_slot(app, admin_client):
    start, end = current_slot()
    sunday = a_sunday_in(start, end)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        present(w, sunday)   # 1 day (the worked Sunday) + however many other Sundays the slot has
        db.session.add(WorkerPayment(worker=w, label="Advance", amount=Decimal("600"), paid_date=start, period_start=start))
        db.session.commit()
        wid = w.id
    row = next(r for r in rows_for(admin_client.get("/api/payroll/overview").get_json(), wid) if r["period_start"] == start.isoformat())
    assert row["paid"] == 600.0
    assert row["outstanding"] == round(row["earned"] - 600.0, 2)


def test_a_payment_tagged_to_a_different_slot_does_not_count_here(app, admin_client):
    start, end = current_slot()
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        other_period = start - timedelta(days=200)   # some other, unrelated period
        db.session.add(WorkerPayment(worker=w, label="Old", amount=Decimal("5000"), paid_date=other_period, period_start=other_period))
        db.session.commit()
        wid = w.id
    row = next(r for r in rows_for(admin_client.get("/api/payroll/overview").get_json(), wid) if r["period_start"] == start.isoformat())
    assert row["paid"] == 0.0


def test_an_untagged_payment_does_not_count_toward_any_slot(app, admin_client):
    """A payment with no period_start at all (an older entry, from before this existed, or one the admin
    just didn't tag) shouldn't be silently guessed into whichever slot its paid_date happens to fall in -
    only an explicit tag matches (kohal's own design: don't retroactively claim old data was for this)."""
    start, end = current_slot()
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        db.session.add(WorkerPayment(worker=w, label="Untagged", amount=Decimal("500"), paid_date=start, period_start=None))
        db.session.commit()
        wid = w.id
    row = next(r for r in rows_for(admin_client.get("/api/payroll/overview").get_json(), wid) if r["period_start"] == start.isoformat())
    assert row["paid"] == 0.0


def test_an_unpaid_entry_with_no_paid_date_does_not_count_as_paid(app, admin_client):
    start, end = current_slot()
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        db.session.add(WorkerPayment(worker=w, label="Planned", amount=Decimal("500"), paid_date=None, period_start=start))
        db.session.commit()
        wid = w.id
    row = next(r for r in rows_for(admin_client.get("/api/payroll/overview").get_json(), wid) if r["period_start"] == start.isoformat())
    assert row["paid"] == 0.0

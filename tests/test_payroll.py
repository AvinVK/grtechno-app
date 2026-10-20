"""Payroll (kohal, 2026-10-20): every employee with a wage set, and what they've earned so far - computed
from attendance, never typed in (see app/payroll.py's own docstring for the exact rules). Dates below are
fixed, not relative to today, so the Sunday-crediting math stays deterministic - 4 and 11 Oct 2026 are both
Sundays."""

from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Worker, WorkerPayment


def daily_wage_worker(name="Deepak Daily", wage_amount=Decimal("500"), first_seen=date(2026, 10, 1),
                       employment_type="daily_wages"):
    worker = Worker(name=name, category="manpower", employment_type=employment_type,
                     wage_amount=wage_amount, first_seen=first_seen)
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
    from app.models import WorkerAttendance
    for d in days:
        db.session.add(WorkerAttendance(worker=worker, work_date=d, check_in_lat=21.1, check_in_lng=79.0))
    db.session.commit()


def months_ago(n):
    """n calendar months back from today, as the 1st of that month - avoids needing dateutil."""
    today = date.today()
    y, m = today.year, today.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


# ---------- module gating ----------

def test_payroll_needs_the_workforce_module(client, accounts_client):
    assert client.get("/payroll").status_code == 403
    assert client.get("/api/payroll/overview").status_code == 403
    assert accounts_client.get("/payroll").status_code == 200
    assert accounts_client.get("/api/payroll/overview").status_code == 200


# ---------- daily wages / contractor: wage x (present days + uncredited Sundays) ----------

def test_daily_wage_earned_is_present_days_plus_uncredited_sundays(app, admin_client):
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=date(2026, 10, 1))
        # 4 Oct and 11 Oct are both Sundays - present on 11th (worked that Sunday), not on the 4th.
        present(w, date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 6), date(2026, 10, 11))
        wid = w.id
    data = admin_client.get("/api/payroll/overview").get_json()
    row = next(e for e in data["employees"] if e["id"] == wid)
    # 4 actual present days + 1 credited Sunday (the 4th - the 11th is already present, not double-paid).
    assert row["days"] == 5
    assert row["earned"] == 2500.0
    assert row["months"] is None


def test_a_worked_sunday_is_not_paid_twice(app, admin_client):
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=date(2026, 10, 1))
        present(w, date(2026, 10, 11))   # only present day is itself a Sunday
        wid = w.id
    data = admin_client.get("/api/payroll/overview").get_json()
    row = next(e for e in data["employees"] if e["id"] == wid)
    # 1 present day (the 11th) + 1 credited Sunday (the 4th, never worked) = 2, not 3.
    assert row["days"] == 2
    assert row["earned"] == 1000.0


def test_sundays_before_first_seen_are_not_credited(app, admin_client):
    with app.app_context():
        # Started on the 6th - the 4th (a Sunday) is before they existed, only the 11th counts.
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=date(2026, 10, 6))
        present(w, date(2026, 10, 11))
        wid = w.id
    data = admin_client.get("/api/payroll/overview").get_json()
    row = next(e for e in data["employees"] if e["id"] == wid)
    assert row["days"] == 1   # just the 11th (present, and a Sunday, counted once)
    assert row["earned"] == 500.0


def test_contractor_uses_the_same_day_rate_math_as_daily_wages(app, admin_client):
    with app.app_context():
        w = daily_wage_worker(name="Clive Contractor", wage_amount=Decimal("700"),
                               first_seen=date(2026, 10, 1), employment_type="contractor")
        # data_until only reaches as far as actual recorded data - the 11th here, so the 4th is the only
        # Sunday that falls inside the counted range at all.
        present(w, date(2026, 10, 1), date(2026, 10, 11))
        wid = w.id
    data = admin_client.get("/api/payroll/overview").get_json()
    row = next(e for e in data["employees"] if e["id"] == wid)
    assert row["employment_type"] == "contractor"
    # 2 present days (1st, 11th) + 1 credited Sunday (the 4th, not already present) = 3.
    assert row["days"] == 3
    assert row["earned"] == 2100.0


# ---------- salary: flat monthly, not attendance-linked ----------

def test_salary_is_flat_times_months_elapsed_not_attendance_linked(app, admin_client):
    with app.app_context():
        w = salaried_worker(wage_amount=Decimal("30000"), first_seen=months_ago(2))
        wid = w.id
        # No attendance at all - must not matter, salary is unconditional (kohal's own pick).
    data = admin_client.get("/api/payroll/overview").get_json()
    row = next(e for e in data["employees"] if e["id"] == wid)
    assert row["months"] == 3   # the start month, the month after, and the current one
    assert row["earned"] == 90000.0
    assert row["days"] is None


def test_salary_counts_the_current_partial_month_in_full(app, admin_client):
    with app.app_context():
        w = salaried_worker(wage_amount=Decimal("30000"), first_seen=date.today().replace(day=1))
        wid = w.id
    data = admin_client.get("/api/payroll/overview").get_json()
    row = next(e for e in data["employees"] if e["id"] == wid)
    assert row["months"] == 1
    assert row["earned"] == 30000.0


# ---------- who shows up at all ----------

def test_an_employee_with_no_wage_set_is_excluded(app, admin_client):
    with app.app_context():
        w = Worker(name="No Wage Nilesh", category="manpower", employment_type="daily_wages")
        db.session.add(w)
        db.session.commit()
        wid = w.id
    data = admin_client.get("/api/payroll/overview").get_json()
    assert wid not in [e["id"] for e in data["employees"]]


def test_an_employee_with_no_employment_type_is_excluded(app, admin_client):
    with app.app_context():
        w = Worker(name="Unset Umesh", category="manpower", wage_amount=Decimal("500"))
        db.session.add(w)
        db.session.commit()
        wid = w.id
    data = admin_client.get("/api/payroll/overview").get_json()
    assert wid not in [e["id"] for e in data["employees"]]


# ---------- outstanding ----------

def test_outstanding_is_earned_minus_paid(app, admin_client):
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=date(2026, 10, 1))
        present(w, date(2026, 10, 1), date(2026, 10, 11))   # 2 present days, 1 credited Sunday = 3, earned 1500
        db.session.add(WorkerPayment(worker=w, label="Advance", amount=Decimal("600"), paid_date=date(2026, 10, 1)))
        db.session.commit()
        wid = w.id
    data = admin_client.get("/api/payroll/overview").get_json()
    row = next(e for e in data["employees"] if e["id"] == wid)
    assert row["earned"] == 1500.0
    assert row["paid"] == 600.0
    assert row["outstanding"] == 900.0


def test_an_unpaid_entry_with_no_paid_date_does_not_count_as_paid(app, admin_client):
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=date(2026, 10, 1))
        present(w, date(2026, 10, 1))
        db.session.add(WorkerPayment(worker=w, label="Planned", amount=Decimal("500"), paid_date=None))
        db.session.commit()
        wid = w.id
    data = admin_client.get("/api/payroll/overview").get_json()
    row = next(e for e in data["employees"] if e["id"] == wid)
    assert row["paid"] == 0.0

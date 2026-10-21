"""Payroll (kohal, 2026-10-20): every employee with a wage set, and what they've earned so far - computed
from attendance, never typed in (see app/payroll.py's own docstring for the exact rules). A daily-wage or
contractor employee gets two rows, one per the *current* month's own pay-period slot (1st-15th, 16th-end) -
dates below are built from date.today() itself (via current_slot()/complete_slot(), test-only helpers, not
the thing being tested) rather than hardcoded, since the slots are always relative to whenever the suite
actually runs."""

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Worker, WorkerAttendance, WorkerPayment
from app.payroll import PAYROLL_START


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


def expected_months(first_seen):
    """Calendar months from first_seen (floored at PAYROLL_START - kohal, 2026-10-21: "payroll calc should
    start from oct 1st") through today, inclusive - a from-first-principles reimplementation independent of
    app/payroll.py's own _months_elapsed, so these tests still make sense whenever the suite actually runs,
    floor or no floor."""
    today = date.today()
    start = max(first_seen, PAYROLL_START)
    return (today.year - start.year) * 12 + (today.month - start.month) + 1


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
    first_seen = months_ago(2)
    with app.app_context():
        w = salaried_worker(wage_amount=Decimal("30000"), first_seen=first_seen)
        wid = w.id
    rows = rows_for(admin_client.get("/api/payroll/overview").get_json(), wid)
    assert len(rows) == 1
    row = rows[0]
    months = expected_months(first_seen)
    assert row["months"] == months
    assert row["earned"] == 30000.0 * months
    assert row["days"] is None and row["period_start"] is None


def test_salary_never_accrues_before_payroll_start(app, admin_client):
    """kohal, 2026-10-21: "payroll calc should start from oct 1st" - someone whose attendance history
    reaches back well before this app ever tracked pay doesn't retroactively owe for any of it; they're
    treated exactly like someone who only started on the floor date itself."""
    with app.app_context():
        old_timer = salaried_worker(name="Old Timer", wage_amount=Decimal("30000"),
                                     first_seen=PAYROLL_START - timedelta(days=200))
        started_at_floor = salaried_worker(name="Started At Floor", wage_amount=Decimal("30000"),
                                            first_seen=PAYROLL_START)
        old_id, floor_id = old_timer.id, started_at_floor.id
    data = admin_client.get("/api/payroll/overview").get_json()
    old_row = rows_for(data, old_id)[0]
    floor_row = rows_for(data, floor_id)[0]
    assert old_row["months"] == floor_row["months"]
    assert old_row["earned"] == floor_row["earned"]


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


# ---------- /api/payroll/days - the day-by-day behind one Overview row ----------

def day_in(days, iso):
    return next(d for d in days if d["date"] == iso)


def test_days_needs_the_workforce_module(client, accounts_client, app):
    start, end = complete_slot()
    with app.app_context():
        wid = daily_wage_worker(first_seen=start).id
        extend_data_until(end)
    url = f"/api/payroll/days?worker_id={wid}&start={start.isoformat()}&end={end.isoformat()}"
    assert client.get(url).status_code == 403
    assert accounts_client.get(url).status_code == 200


def test_a_present_day_with_in_and_out_times_shows_hours(app, admin_client):
    start, end = complete_slot()
    worked_day = a_weekday_in(start, end)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        db.session.add(WorkerAttendance(worker=w, work_date=worked_day,
                                         check_in_at=datetime.combine(worked_day, datetime.min.time().replace(hour=8)),
                                         check_out_at=datetime.combine(worked_day, datetime.min.time().replace(hour=17))))
        extend_data_until(end)
        db.session.commit()
        wid = w.id
    res = admin_client.get(f"/api/payroll/days?worker_id={wid}&start={start.isoformat()}&end={end.isoformat()}")
    assert res.status_code == 200
    d = day_in(res.get_json()["days"], worked_day.isoformat())
    assert d["present"] is True and d["hours"] == 9.0 and d["pay"] == 500.0


def test_a_present_day_with_no_times_has_no_hours_but_is_still_paid(app, admin_client):
    start, end = complete_slot()
    worked_day = a_weekday_in(start, end)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        present(w, worked_day)   # the shared helper - no check-in/out times, just lat/lng
        extend_data_until(end)
        wid = w.id
    res = admin_client.get(f"/api/payroll/days?worker_id={wid}&start={start.isoformat()}&end={end.isoformat()}")
    d = day_in(res.get_json()["days"], worked_day.isoformat())
    assert d["present"] is True and d["hours"] is None and d["pay"] == 500.0


def test_an_absent_weekday_is_zero_pay(app, admin_client):
    start, end = complete_slot()
    worked_day = a_weekday_in(start, end)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        extend_data_until(end)   # nothing present for this worker at all
        wid = w.id
    res = admin_client.get(f"/api/payroll/days?worker_id={wid}&start={start.isoformat()}&end={end.isoformat()}")
    d = day_in(res.get_json()["days"], worked_day.isoformat())
    assert d["present"] is False and d["pay"] == 0.0 and d["not_yet"] is False


def test_an_unworked_sunday_is_credited_in_the_day_list_too(app, admin_client):
    start, end = complete_slot()
    sunday = a_sunday_in(start, end)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        extend_data_until(end)
        wid = w.id
    res = admin_client.get(f"/api/payroll/days?worker_id={wid}&start={start.isoformat()}&end={end.isoformat()}")
    d = day_in(res.get_json()["days"], sunday.isoformat())
    assert d["present"] is False and d["is_sunday"] is True and d["pay"] == 500.0


def test_a_day_before_first_seen_is_not_yet_and_a_sunday_there_is_not_credited(app, admin_client):
    """Matches _day_rate_slot_row's own effective_start guard - otherwise this list's own total would come
    out different from the "Total" figure above it, computed the same way but period-wide."""
    start, end = complete_slot()
    sunday = a_sunday_in(start, end)
    joined = sunday + timedelta(days=1)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=joined)
        extend_data_until(end)
        wid = w.id
    res = admin_client.get(f"/api/payroll/days?worker_id={wid}&start={start.isoformat()}&end={end.isoformat()}")
    d = day_in(res.get_json()["days"], sunday.isoformat())
    assert d["not_yet"] is True and d["pay"] == 0.0


def test_a_day_before_payroll_start_is_not_yet_even_if_first_seen_reaches_further_back(app, admin_client):
    """kohal, 2026-10-21: "payroll calc should start from oct 1st" - same not_yet guard as first_seen's
    own, just with PAYROLL_START as a second, shared floor on top of it."""
    before = PAYROLL_START - timedelta(days=3)
    after = PAYROLL_START + timedelta(days=2)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=PAYROLL_START - timedelta(days=200))
        extend_data_until(after)
        wid = w.id
    res = admin_client.get(f"/api/payroll/days?worker_id={wid}&start={before.isoformat()}&end={after.isoformat()}")
    days = res.get_json()["days"]
    assert day_in(days, before.isoformat())["not_yet"] is True
    assert day_in(days, PAYROLL_START.isoformat())["not_yet"] is False


def test_salary_days_have_no_per_day_pay_figure(app, admin_client):
    with app.app_context():
        w = salaried_worker(wage_amount=Decimal("30000"), first_seen=date.today().replace(day=1))
        today = date.today()
        present(w, today)
        wid = w.id
    start = date.today().replace(day=1).isoformat()
    end = date.today().isoformat()
    res = admin_client.get(f"/api/payroll/days?worker_id={wid}&start={start}&end={end}")
    assert res.status_code == 200
    for d in res.get_json()["days"]:
        assert d["pay"] is None


def test_an_unknown_worker_is_a_404(admin_client):
    res = admin_client.get("/api/payroll/days?worker_id=999999&start=2026-10-01&end=2026-10-15")
    assert res.status_code == 404


def test_a_worker_with_no_wage_is_a_404(app, admin_client):
    with app.app_context():
        w = Worker(name="No Wage", category="manpower", employment_type="daily_wages")
        db.session.add(w)
        db.session.commit()
        wid = w.id
    res = admin_client.get(f"/api/payroll/days?worker_id={wid}&start=2026-10-01&end=2026-10-15")
    assert res.status_code == 404


def test_end_before_start_is_rejected(app, admin_client):
    with app.app_context():
        wid = daily_wage_worker().id
    res = admin_client.get(f"/api/payroll/days?worker_id={wid}&start=2026-10-15&end=2026-10-01")
    assert res.status_code == 422


def test_a_huge_range_is_rejected(app, admin_client):
    with app.app_context():
        wid = daily_wage_worker().id
    res = admin_client.get(f"/api/payroll/days?worker_id={wid}&start=2026-01-01&end=2026-12-31")
    assert res.status_code == 422


# ---------- /api/payroll/periods - a daily-wage/contractor person's cycles, current and previous ----------
#
# kohal, 2026-10-20: "it should open consolidates 15 days cycles. current and previous. along with its
# total dues" - the screen between Overview and one cycle's own day-by-day.

def prev_slot(start):
    """The slot immediately before the one that starts on `start` - test infrastructure only, a plain
    reimplementation independent of app/payroll.py's own _day_rate_periods (the thing under test)."""
    if start.day == 16:
        return date(start.year, start.month, 1), date(start.year, start.month, 15)
    prev_month_last = start - timedelta(days=1)
    return date(prev_month_last.year, prev_month_last.month, 16), prev_month_last


def test_periods_needs_the_workforce_module(client, accounts_client, app):
    with app.app_context():
        wid = daily_wage_worker().id
    url = f"/api/payroll/periods?worker_id={wid}"
    assert client.get(url).status_code == 403
    assert accounts_client.get(url).status_code == 200


def test_a_worker_who_started_this_slot_has_only_the_current_one(app, admin_client):
    start, _ = current_slot()
    with app.app_context():
        wid = daily_wage_worker(first_seen=start).id
    res = admin_client.get(f"/api/payroll/periods?worker_id={wid}")
    assert res.status_code == 200
    body = res.get_json()
    assert len(body["periods"]) == 1
    assert body["periods"][0]["period_start"] == start.isoformat()
    assert body["total_outstanding"] == body["periods"][0]["outstanding"]


def test_periods_go_back_to_first_seen_current_first(app, admin_client):
    """Goes back to first_seen, but never earlier than PAYROLL_START even when first_seen reaches further
    back than that (kohal, 2026-10-21: "payroll calc should start from oct 1st") - expected_starts is
    filtered the same way whether or not that floor actually bites for whenever this suite happens to run."""
    start, end = current_slot()
    one_back_start, _ = prev_slot(start)
    two_back_start, _ = prev_slot(one_back_start)
    with app.app_context():
        wid = daily_wage_worker(first_seen=two_back_start).id
        extend_data_until(end)
    res = admin_client.get(f"/api/payroll/periods?worker_id={wid}")
    assert res.status_code == 200
    periods = res.get_json()["periods"]
    expected_starts = [s for s in (start, one_back_start, two_back_start) if s >= PAYROLL_START]
    assert [p["period_start"] for p in periods] == [s.isoformat() for s in expected_starts]


def test_periods_each_carry_their_own_earned_paid_outstanding(app, admin_client):
    start, end = complete_slot()
    worked_day = a_weekday_in(start, end)
    sundays = 0
    d = start
    while d <= end:
        if d.weekday() == 6 and d != worked_day:
            sundays += 1
        d += timedelta(days=1)
    with app.app_context():
        w = daily_wage_worker(wage_amount=Decimal("500"), first_seen=start)
        present(w, worked_day)
        db.session.add(WorkerPayment(worker=w, label="Advance", amount=Decimal("200"),
                                      paid_date=end, period_start=start))
        extend_data_until(end)
        wid = w.id
    res = admin_client.get(f"/api/payroll/periods?worker_id={wid}")
    assert res.status_code == 200
    row = next(p for p in res.get_json()["periods"] if p["period_start"] == start.isoformat())
    expected_earned = 500.0 * (1 + sundays)
    assert row["earned"] == expected_earned and row["paid"] == 200.0 and row["outstanding"] == expected_earned - 200.0


def test_total_outstanding_is_the_sum_of_every_period_shown(app, admin_client):
    start, end = current_slot()
    one_back_start, _ = prev_slot(start)
    with app.app_context():
        wid = daily_wage_worker(first_seen=one_back_start).id
        extend_data_until(end)
    res = admin_client.get(f"/api/payroll/periods?worker_id={wid}")
    body = res.get_json()
    assert body["total_outstanding"] == round(sum(p["outstanding"] for p in body["periods"]), 2)


def test_a_contractor_also_gets_periods(app, admin_client):
    start, _ = current_slot()
    with app.app_context():
        wid = daily_wage_worker(employment_type="contractor", first_seen=start).id
    res = admin_client.get(f"/api/payroll/periods?worker_id={wid}")
    assert res.status_code == 200 and len(res.get_json()["periods"]) == 1


def test_a_salaried_worker_has_no_periods(app, admin_client):
    """Pay isn't period-sliced for a salaried employee - nothing for this endpoint to show."""
    with app.app_context():
        wid = salaried_worker().id
    res = admin_client.get(f"/api/payroll/periods?worker_id={wid}")
    assert res.status_code == 404


def test_periods_unknown_or_unwaged_worker_is_a_404(app, admin_client):
    assert admin_client.get("/api/payroll/periods?worker_id=999999").status_code == 404
    with app.app_context():
        w = Worker(name="No Wage", category="manpower", employment_type="daily_wages")
        db.session.add(w)
        db.session.commit()
        wid = w.id
    assert admin_client.get(f"/api/payroll/periods?worker_id={wid}").status_code == 404

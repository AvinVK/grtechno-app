"""Payroll (kohal, 2026-10-20: "we will need a payroll tab inside manage itself. that will have the
employee with already entered daily wages or salary mentioned. then baased on their attendance, their
wages will be calculated as running sum"): two subtabs, same shape as Work plan/Announcements -

  - Overview: every employee with a wage set, and what they've earned so far - computed, never typed in,
    see _payroll_rows below for exactly how. Daily-wage and contractor employees are split into this
    month's two pay-period slots, 1st-15th and 16th-end (kohal, 2026-10-20: "Daily wages should have two
    slots in month 1 to 15 And 16 to 30 or 31 And regular employees monthly salary") - a salaried employee
    stays one flat monthly row, unsplit. Only the current month's two slots are ever shown, never a running
    history of past ones: a payment's own period tag (WorkerPayment.period_start, added alongside this) is
    brand new, so an older payment that predates it has no period on it at all - showing every past slot as
    "outstanding" the moment this ships would make every one of those look unpaid, when really they just
    were never tagged. Scoping to the current month only sidesteps that entirely.
  - Wages & payments: who's owed what, without having to look anyone up first (kohal, 2026-10-20: "i dont
    have to pick anyone, in wages and payment, it should have daily wages and salaried subtab. in daily
    wages, it should show all daily wages user and according to attendance their due pay and last paid.
    same for salaried but on month level") - its own two sub-tabs, Daily wages and Salaried, each a plain
    list (every employee of that kind, what they're currently due - both of this month's slots added
    together for a daily-wage/contractor employee - and their own most recent paid entry). Tapping a
    person opens the add/edit/delete payment log itself, moved here from the Attendance sheet's own person
    page (kohal, in an earlier message: "remove the paymant thing inside the attendance and move it here")
    - the data and its API are unchanged (still a Worker's own `payments`, still saved through
    app/workers.py's PATCH /api/workforce/<id>), only the page it's reached from. Each entry can now also
    carry which pay period it was for (see app/workers.py's own _payments), so both the per-slot "paid"
    figure here and on Overview mean something, and so "last paid" can say which period it covered.

Gated by the "workforce" module (app/modules.py), same as Employee management - a look-only role
(Accountant, Office Assistant) can see Overview and look at payments but not add/edit/remove one."""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, abort, g, jsonify, render_template, request

from .extensions import db
from .models import Attendance, Worker, WorkerAttendance, settings_for_client
from .modules import can_write, check_module
from .validation import api_errors
from .workers import EMPLOYMENT_TYPES, _period

DAY_BY_DAY_MAX_RANGE = 62   # a pay-period slot is ~16 days, a month ~31 - this is generous headroom, not a real limit
MAX_PERIODS = 24   # a year's worth of slots back from the current one - plenty for "current and previous", not unbounded

# Nothing payroll computes ever reaches earlier than this (kohal, 2026-10-21: "payroll calc should start
# from oct 1st") - a lot of worker.first_seen dates reach back through WhatsApp-imported attendance from
# well before this app tracked pay at all, and that history was already settled outside it; this is the
# floor every "how long have they been earning" figure below gets clamped to, on top of each worker's own
# first_seen (see _payroll_start).
PAYROLL_START = date(2026, 10, 1)

bp = Blueprint("payroll", __name__)
api_errors(bp)

# daily_wages and contractor are both a day rate, not a lump sum (kohal, 2026-10-20: "contractor are also
# on daily wages. the users which have daily wages selected in the form should be considered on daily
# wages") - only "regular" (salary) gets the flat monthly treatment below.
DAY_RATE_TYPES = ("daily_wages", "contractor")

MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@bp.before_request
def _payroll_access():
    check_module("workforce")


@bp.get("/payroll")
def page():
    return render_template("payroll.html", can_write=can_write(g.user, "workforce"))


def _months_elapsed(start: date, today: date) -> int:
    """Full calendar months from start's month through today's month, inclusive - salary is flat and
    unconditional (kohal picked this over pro-rating by attendance), so the current month counts in full
    from day one, same as salary accrues from the start of the month regardless of which day you're
    looking at this."""
    return (today.year - start.year) * 12 + (today.month - start.month) + 1


def _sundays_not_present(start: date, end: date, present: set) -> int:
    """Every Sunday in [start, end] that isn't already a present day - a guaranteed paid day off (kohal,
    2026-10-20: "both daily wages and salaried gets 4 leaves a month", meaning Sundays, not an absence
    allowance) on top of whatever they actually worked, never double-paid against a Sunday they did work."""
    count = 0
    d = start + timedelta(days=(6 - start.weekday()) % 7)   # the first Sunday on or after start
    while d <= end:
        if d not in present:
            count += 1
        d += timedelta(days=7)
    return count


def _absent_days(start: date, end: date, present: set) -> int:
    """Every non-Sunday day in [start, end] not in `present` - how many days someone simply didn't show up
    (kohal, 2026-10-21: "once 15 days are over, it should show a flag saying 15 days cycle total is this
    much, u were absent this much"). A Sunday is never "absent" here, same reasoning _sundays_not_present
    already pays it regardless - there's nothing to be absent from."""
    count = 0
    d = start
    while d <= end:
        if d.weekday() != 6 and d not in present:
            count += 1
        d += timedelta(days=1)
    return count


def _payroll_start(w):
    """The earliest day this worker's payroll ever counts from - their own first_seen, floored at
    PAYROLL_START (kohal, 2026-10-21: "payroll calc should start from oct 1st"), or None if they have no
    first_seen at all (nothing to compute from either way, same as before this floor existed)."""
    return max(w.first_seen, PAYROLL_START) if w.first_seen else None


def _current_month_slots(today: date):
    """This month's own two pay-period slots, in order: (start, end, label) each."""
    last_day = calendar.monthrange(today.year, today.month)[1]
    bounds = [(1, 15), (16, last_day)]
    return [
        (date(today.year, today.month, d1), date(today.year, today.month, d2),
         f"{d1}–{d2} {MONTH_ABBR[today.month]} {today.year}")
        for d1, d2 in bounds
    ]


def _last_paid(w):
    """This worker's own most recent paid entry - amount, when, and whichever pay period it was tagged to
    (kohal, 2026-10-20: "it should show all daily wages user and according to attendance their due pay and
    last paid"), or None if they've never had one. Same across every row a worker has (daily-wage/contractor
    get two, one per slot) - it's a fact about the person, not about any one slot."""
    paid = [p for p in w.payments if p.paid_date is not None]
    if not paid:
        return None
    latest = max(paid, key=lambda p: p.paid_date)
    return {
        "amount": float(latest.amount), "paid_date": latest.paid_date.isoformat(),
        "period_start": latest.period_start.isoformat() if latest.period_start else None,
    }


def _day_rate_slot_row(w, slot_start, slot_end, label, data_until_end):
    """One daily-wage/contractor employee's figures for a single pay-period slot - 0 across the board if
    they hadn't started yet, or there's no attendance data reaching this far."""
    wage = float(w.wage_amount)
    days = 0
    absent = 0
    payroll_start = _payroll_start(w)
    effective_start = max(slot_start, payroll_start) if payroll_start else None
    effective_end = min(slot_end, data_until_end) if data_until_end else None
    if effective_start and effective_end and effective_end >= effective_start:
        present = {a.work_date for a in WorkerAttendance.query.filter_by(worker_id=w.id, status="present")
                   .filter(WorkerAttendance.work_date >= effective_start, WorkerAttendance.work_date <= effective_end)}
        if w.user_code:
            present |= {a.work_date for a in Attendance.query.filter_by(user_code=w.user_code, status="approved")
                        .filter(Attendance.work_date >= effective_start, Attendance.work_date <= effective_end)}
        days = len(present) + _sundays_not_present(effective_start, effective_end, present)
        absent = _absent_days(effective_start, effective_end, present)
    earned = round(wage * days, 2)
    paid = float(sum((p.amount for p in w.payments if p.period_start == slot_start and p.paid_date is not None),
                      start=Decimal("0")))
    return {
        "id": w.id, "name": w.name, "employment_type": w.employment_type, "wage_amount": wage,
        "months": None, "days": days, "absent": absent,
        "period_start": slot_start.isoformat(), "period_end": slot_end.isoformat(), "period_label": label,
        "earned": earned, "paid": paid, "outstanding": round(earned - paid, 2), "last_paid": _last_paid(w),
    }


def _day_rate_periods(w, today: date, data_until_end):
    """Every pay-period slot behind one daily-wage/contractor employee, current first and going back to
    whenever they first showed up (or MAX_PERIODS slots, whichever is shorter) - each with its own
    earned/paid/outstanding, same figures _current_month_slots' two rows already use (kohal, 2026-10-20: "it
    should open consolidates 15 days cycles. current and previous. along with its total dues"). A payment
    made before WorkerPayment.period_start existed has no period tag to match against, so a slot from before
    that still shows as fully outstanding even if it was actually paid at the time - same caveat
    _payroll_rows' own current-month-only scoping was written to dodge, now accepted deliberately since
    seeing the history is the whole point of this list."""
    periods = []
    y, m = today.year, today.month
    half = 1 if today.day <= 15 else 2
    limit_date = _payroll_start(w) or today
    while len(periods) < MAX_PERIODS:
        last_day = calendar.monthrange(y, m)[1]
        d1, d2 = (1, 15) if half == 1 else (16, last_day)
        slot_start = date(y, m, d1)
        slot_end = date(y, m, d2)
        if slot_end < limit_date:
            break
        label = f"{d1}–{d2} {MONTH_ABBR[m]} {y}"
        periods.append(_day_rate_slot_row(w, slot_start, slot_end, label, data_until_end))
        # Step to the previous (older) slot: 16th-end steps back to the same month's 1st-15th; 1st-15th
        # steps back to the *previous* month's 16th-end.
        if half == 2:
            half = 1
        else:
            half = 2
            m -= 1
            if m == 0:
                m = 12
                y -= 1
    return periods


def _payroll_rows() -> list:
    """One row per employee with a wage set (two, for a daily-wage/contractor one - see this module's own
    docstring) - nobody with no wage_amount shows here, there's nothing to compute from. 'earned' is always
    computed fresh from attendance (or elapsed months, for salary), never stored - same philosophy as a
    project's own Materials used or Daily wages (app/projects.py)."""
    _, data_until = _period()
    today = date.today()
    data_until_end = min(today, data_until) if data_until else None
    slots = _current_month_slots(today)

    rows = []
    workers = (Worker.query
               .filter(Worker.employment_type.in_(EMPLOYMENT_TYPES), Worker.wage_amount.isnot(None))
               .order_by(Worker.name).all())
    for w in workers:
        if w.employment_type == "regular":
            wage = float(w.wage_amount)
            payroll_start = _payroll_start(w)
            months = max(0, _months_elapsed(payroll_start, today)) if payroll_start else 0
            earned = round(wage * months, 2)
            paid = float(w.paid_amount)
            rows.append({
                "id": w.id, "name": w.name, "employment_type": w.employment_type, "wage_amount": wage,
                "months": months, "days": None, "period_start": None, "period_end": None, "period_label": None,
                "earned": earned, "paid": paid, "outstanding": round(earned - paid, 2), "last_paid": _last_paid(w),
            })
        else:
            for slot_start, slot_end, label in slots:
                rows.append(_day_rate_slot_row(w, slot_start, slot_end, label, data_until_end))
    return rows


def _day_by_day(w, start: date, end: date, data_until_end):
    """One row per calendar day in [start, end] - hours logged that day (if any - needs both a check-in
    and a check-out time to say, same as Attendance/WorkerAttendance's own `hours`), and whether it counts
    toward pay (present, or an uncredited Sunday - the same rule _day_rate_slot_row uses) with the rupee
    figure that represents (kohal, 2026-10-20: "clicking on one should show logged in hours for each day
    and corresponding pay"). A day past whatever attendance data actually reaches is left blank, not
    guessed at - same "no data yet" principle as everywhere else attendance is read in this app."""
    is_day_rate = w.employment_type in DAY_RATE_TYPES
    wage = float(w.wage_amount) if w.wage_amount is not None else 0.0
    payroll_start = _payroll_start(w)
    wa_by_day = {a.work_date: a for a in WorkerAttendance.query.filter_by(worker_id=w.id)
                 .filter(WorkerAttendance.work_date >= start, WorkerAttendance.work_date <= end)}
    att_by_day = {}
    if w.user_code:
        for a in (Attendance.query.filter_by(user_code=w.user_code, status="approved")
                  .filter(Attendance.work_date >= start, Attendance.work_date <= end)):
            att_by_day.setdefault(a.work_date, []).append(a)

    rows = []
    d = start
    while d <= end:
        is_sunday = d.weekday() == 6
        # Before they'd even first shown up, or past whatever data actually reaches - either way nothing
        # to say about the day, and a Sunday here must not be credited (same first_seen guard
        # _day_rate_slot_row's own effective_start applies) - otherwise this list's own total would come
        # out higher than the "Total" above it, computed the same way but period-wide.
        too_early = payroll_start is not None and d < payroll_start
        if too_early or data_until_end is None or d > data_until_end:
            rows.append({"date": d.isoformat(), "present": False, "hours": None, "is_sunday": is_sunday,
                         "not_yet": True, "pay": 0.0 if is_day_rate else None})
            d += timedelta(days=1)
            continue
        wa = wa_by_day.get(d)
        present = (wa is not None and wa.status == "present") or d in att_by_day
        hours = None
        if wa is not None and wa.status == "present" and wa.hours is not None:
            hours = wa.hours
        elif d in att_by_day:
            timed = [a.hours for a in att_by_day[d] if a.hours is not None]
            if timed:
                hours = round(sum(timed), 1)
        counted = present or is_sunday
        # A day rate genuinely has a per-day figure; a flat salary doesn't (kohal picked unconditional,
        # not pro-rated, when this was built) - pay stays null for a salaried employee's days rather than
        # attributing a whole month's salary to one day, or inventing a daily rate nobody set.
        pay = (round(wage, 2) if counted else 0.0) if is_day_rate else None
        rows.append({"date": d.isoformat(), "present": present, "hours": hours, "is_sunday": is_sunday,
                     "not_yet": False, "pay": pay})
        d += timedelta(days=1)
    return rows


@bp.get("/api/payroll/overview")
def overview():
    return jsonify(employees=_payroll_rows(), currency=settings_for_client()["currency"])


@bp.get("/api/payroll/periods")
def periods():
    """Every pay-period cycle behind one daily-wage/contractor Overview row, current first (kohal,
    2026-10-20: "it should open consolidates 15 days cycles. current and previous. along with its total
    dues") - the screen between Overview and one cycle's own day-by-day (app/static/js/payroll.js's
    showPersonPeriods). Salaried has no such cycle - pay isn't period-sliced for them (see _payroll_rows'
    own docstring) - so there's nothing for this endpoint to return for one; the frontend never calls it for
    a regular employee, straight to the days view instead."""
    worker = db.session.get(Worker, request.args.get("worker_id", type=int))
    if worker is None or worker.wage_amount is None or worker.employment_type not in DAY_RATE_TYPES:
        abort(404)
    _, data_until = _period()
    today = date.today()
    data_until_end = min(today, data_until) if data_until else None
    rows = _day_rate_periods(worker, today, data_until_end)
    return jsonify(
        worker={"id": worker.id, "name": worker.name, "employment_type": worker.employment_type,
                "wage_amount": float(worker.wage_amount)},
        periods=rows,
        total_outstanding=round(sum(r["outstanding"] for r in rows), 2),
        currency=settings_for_client()["currency"],
    )


@bp.get("/api/payroll/days")
def days():
    """The day-by-day breakdown behind one Overview row - a daily-wage/contractor slot's own start/end, or
    whatever range the caller asks for (Overview passes this month's days-so-far for a salaried row, since
    their pay isn't actually day-based - see app/static/js/payroll.js)."""
    worker = db.session.get(Worker, request.args.get("worker_id", type=int))
    if worker is None or worker.wage_amount is None:
        abort(404)
    start = request.args.get("start")
    end = request.args.get("end")
    try:
        start = date.fromisoformat(start)
        end = date.fromisoformat(end)
    except (TypeError, ValueError):
        abort(422, "Give start and end as YYYY-MM-DD")
    if end < start or (end - start).days > DAY_BY_DAY_MAX_RANGE:
        abort(422, "That range doesn't make sense")

    _, data_until = _period()
    today = date.today()
    data_until_end = min(today, data_until) if data_until else None
    return jsonify(
        worker={"id": worker.id, "name": worker.name, "employment_type": worker.employment_type,
                "wage_amount": float(worker.wage_amount)},
        days=_day_by_day(worker, start, end, data_until_end),
        currency=settings_for_client()["currency"],
    )

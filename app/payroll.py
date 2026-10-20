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

from flask import Blueprint, g, jsonify, render_template

from .models import Attendance, Worker, WorkerAttendance, settings_for_client
from .modules import can_write, check_module
from .validation import api_errors
from .workers import EMPLOYMENT_TYPES, _period

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
    effective_start = max(slot_start, w.first_seen) if w.first_seen else None
    effective_end = min(slot_end, data_until_end) if data_until_end else None
    if effective_start and effective_end and effective_end >= effective_start:
        present = {a.work_date for a in WorkerAttendance.query.filter_by(worker_id=w.id, status="present")
                   .filter(WorkerAttendance.work_date >= effective_start, WorkerAttendance.work_date <= effective_end)}
        if w.user_code:
            present |= {a.work_date for a in Attendance.query.filter_by(user_code=w.user_code, status="approved")
                        .filter(Attendance.work_date >= effective_start, Attendance.work_date <= effective_end)}
        days = len(present) + _sundays_not_present(effective_start, effective_end, present)
    earned = round(wage * days, 2)
    paid = float(sum((p.amount for p in w.payments if p.period_start == slot_start and p.paid_date is not None),
                      start=Decimal("0")))
    return {
        "id": w.id, "name": w.name, "employment_type": w.employment_type, "wage_amount": wage,
        "months": None, "days": days,
        "period_start": slot_start.isoformat(), "period_end": slot_end.isoformat(), "period_label": label,
        "earned": earned, "paid": paid, "outstanding": round(earned - paid, 2), "last_paid": _last_paid(w),
    }


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
            months = max(0, _months_elapsed(w.first_seen, today)) if w.first_seen else 0
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


@bp.get("/api/payroll/overview")
def overview():
    return jsonify(employees=_payroll_rows(), currency=settings_for_client()["currency"])

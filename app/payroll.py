"""Payroll (kohal, 2026-10-20: "we will need a payroll tab inside manage itself. that will have the
employee with already entered daily wages or salary mentioned. then baased on their attendance, their
wages will be calculated as running sum"): two subtabs, same shape as Work plan/Announcements -

  - Overview: every employee with a wage set, and what they've earned so far - computed, never typed in,
    see _payroll_rows below for exactly how.
  - Wages & payments: the add/edit/delete payment log itself, moved here from the Attendance sheet's own
    person page (kohal: "remove the paymant thing inside the attendance and move it here") - the data and
    its API are unchanged (still a Worker's own `payments`, still saved through app/workers.py's PATCH
    /api/workforce/<id>), only the page it's reached from.

Gated by the "workforce" module (app/modules.py), same as Employee management - a look-only role
(Accountant, Office Assistant) can see Overview and look at payments but not add/edit/remove one."""

from datetime import date, timedelta

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


def _payroll_rows() -> list:
    """One row per employee with a wage set - nobody with no wage_amount shows here, there's nothing to
    compute from. 'earned' is always computed fresh from attendance (or elapsed months, for salary), never
    stored - same philosophy as a project's own Materials used or Daily wages (app/projects.py)."""
    _, data_until = _period()
    today = date.today()
    end = min(today, data_until) if data_until else None

    rows = []
    workers = (Worker.query
               .filter(Worker.employment_type.in_(EMPLOYMENT_TYPES), Worker.wage_amount.isnot(None))
               .order_by(Worker.name).all())
    for w in workers:
        wage = float(w.wage_amount)
        months = days = None
        if w.employment_type == "regular":
            if w.first_seen:
                months = max(0, _months_elapsed(w.first_seen, today))
            earned = wage * (months or 0)
        else:
            if w.first_seen and end and end >= w.first_seen:
                present = {a.work_date for a in WorkerAttendance.query.filter_by(worker_id=w.id, status="present")
                           .filter(WorkerAttendance.work_date <= end)}
                if w.user_code:
                    present |= {a.work_date for a in Attendance.query.filter_by(user_code=w.user_code, status="approved")
                                .filter(Attendance.work_date <= end)}
                present_days = sum(1 for d in present if d >= w.first_seen)
                days = present_days + _sundays_not_present(w.first_seen, end, present)
            earned = wage * (days or 0)
        earned = round(earned, 2)
        paid = float(w.paid_amount)
        rows.append({
            "id": w.id, "name": w.name, "employment_type": w.employment_type, "wage_amount": wage,
            "months": months, "days": days, "earned": earned, "paid": paid,
            "outstanding": round(earned - paid, 2),
        })
    return rows


@bp.get("/api/payroll/overview")
def overview():
    return jsonify(employees=_payroll_rows(), currency=settings_for_client()["currency"])

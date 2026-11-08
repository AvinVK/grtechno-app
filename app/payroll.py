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

  - Payment sheet (kohal, 2026-11-08: "this is now the payslip is suppose to look, is it possible to show in the app and then
    have excel downloadable?"): one month, one row per salaried employee, laid out like the sheet kohal shared - salary, days
    present and absent, the month's salary after absences, house rent / petrol, the advance columns and what is left to pay -
    and the same thing as an Excel file. See salaried_month / payment_sheet below.

Salary is cut for absences (kohal, 2026-11-08, answered: "Cut for absences" - it used to be the full salary whatever the
attendance): salary per day = monthly salary / days in the month, rounded to the rupee; a month with no absences pays the full
salary, otherwise salary per day x days present. Sundays are paid days off, the same rule daily wages use, so "present" counts
them, and so does approved paid leave (app/leaves.py); an unpaid leave day is cut like an absence. Days that have not happened yet (or that attendance data does not reach yet) are never counted absent.

Gated by the "workforce" module (app/modules.py), same as Employee management - a look-only role
(Accountant, Office Assistant) can see Overview and look at payments but not add/edit/remove one."""

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, Response, abort, g, jsonify, render_template, request

from .advances import add_months, deduction_to_date, instalments, month_deduction, slot_deduction
from .extensions import db
from .leaves import balance as leave_balance, month_tally, paid_leave_days
from .models import Attendance, Worker, WorkerAttendance, settings_for_client
from .modules import can_write, check_module
from .timeutil import today_local
from .validation import api_errors
from .workers import EMPLOYMENT_TYPES, _period
from .xlsx import _col, build_workbook

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
    """Calendar months from start's month through today's month, inclusive."""
    return (today.year - start.year) * 12 + (today.month - start.month) + 1


def _present_days(w, start: date, end: date) -> set:
    """Every day in [start, end] this employee was present - a recorded day (WhatsApp import or added by hand) or an approved
    check-in of their own."""
    present = {a.work_date for a in WorkerAttendance.query.filter_by(worker_id=w.id, status="present")
               .filter(WorkerAttendance.work_date >= start, WorkerAttendance.work_date <= end)}
    if w.user_code:
        present |= {a.work_date for a in Attendance.query.filter_by(user_code=w.user_code, status="approved")
                    .filter(Attendance.work_date >= start, Attendance.work_date <= end)}
    return present


def salaried_month(w, year: int, month: int, data_until_end) -> dict | None:
    """One salaried employee's salary for one calendar month (see this module's docstring for the rule), or None if they had
    not started by the month's end. Days before they started are neither paid nor absent."""
    first = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    last = date(year, month, days_in_month)
    start = max(first, _payroll_start(w))
    if start > last:
        return None
    salary = Decimal(w.wage_amount)
    per_day = (salary / days_in_month).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    known_end = min(last, data_until_end) if data_until_end else None
    absent, recorded = 0, 0
    if known_end is not None and known_end >= start:
        present = _present_days(w, start, known_end)
        on_paid_leave = {d for d, (_, paid) in paid_leave_days(w, start, known_end).items() if paid}
        absent, recorded = _absent_days(start, known_end, present | on_paid_leave), len(present | on_paid_leave)
    before_start = (start - first).days
    paid_days = days_in_month - before_start - absent
    net = salary if paid_days == days_in_month else per_day * paid_days
    return {
        "from": start, "to": last, "salary": salary, "days_in_month": days_in_month, "per_day": per_day,
        "present": paid_days, "absent": absent, "cut": salary - net, "net": net,
        "allowance": Decimal(w.allowance_amount or 0),
        # Not one day recorded present: likely their attendance just isn't being recorded, rather than a month away - flagged on
        # the payment sheet so it is checked before paying.
        "no_attendance": recorded == 0 and absent > 0,
        # Whether attendance data reaches the month's end; if not (the month is still going), absences are counted up to
        # counted_until only (None: no attendance data at all yet).
        "complete": known_end is not None and known_end >= last, "counted_until": known_end,
    }


def _salaried_earned(w, today: date, data_until_end) -> Decimal:
    """Everything a salaried employee has earned from payroll's start through this month: each month's salary after absences,
    plus house rent / petrol."""
    total = Decimal("0")
    month = _payroll_start(w).replace(day=1)
    while month <= today.replace(day=1):
        m = salaried_month(w, month.year, month.month, data_until_end)
        if m:
            total += m["net"] + m["allowance"]
        month = add_months(month, 1)
    return total


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
    """The earliest day this worker's payroll ever counts from - PAYROLL_START (kohal, 2026-10-21: "payroll
    calc should start from oct 1st"), or their own first_seen if that's later still. first_seen is only
    ever set by the old WhatsApp-import flow - nothing in this app writes it - so most employees added
    straight through Employee management simply never get one; that must not read as "hasn't started yet"
    and zero out every figure below forever (kohal, 2026-10-21, reported against Meraj specifically: "it
    shows zero due but the attendance shows he should be having dues" - his own day-by-day had real
    attendance the whole time, only the period/month totals were collapsing to 0 for want of a first_seen
    that nothing in this app was ever going to set)."""
    return max(w.first_seen, PAYROLL_START) if w.first_seen else PAYROLL_START


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
    this slot is entirely before their own first_seen (when they have one on file), or there's no
    attendance data reaching this far yet."""
    wage = float(w.wage_amount)
    days = 0
    absent = 0
    effective_start = max(slot_start, _payroll_start(w))
    effective_end = min(slot_end, data_until_end) if data_until_end else None
    if effective_start and effective_end and effective_end >= effective_start:
        present = _present_days(w, effective_start, effective_end)
        days = len(present) + _sundays_not_present(effective_start, effective_end, present)
        absent = _absent_days(effective_start, effective_end, present)
    earned = round(wage * days, 2)
    paid = float(sum((p.amount for p in w.payments if p.period_start == slot_start and p.paid_date is not None),
                      start=Decimal("0")))
    # What is being taken back from this period for any salary advance (kohal, 2026-11-06) - see app/advances.py.
    deduction = float(slot_deduction(w, slot_start))
    return {
        "id": w.id, "name": w.name, "employment_type": w.employment_type, "wage_amount": wage,
        "months": None, "days": days, "absent": absent,
        "period_start": slot_start.isoformat(), "period_end": slot_end.isoformat(), "period_label": label,
        "earned": earned, "paid": paid, "advance_deduction": deduction, "outstanding": round(earned - paid - deduction, 2),
        "last_paid": _last_paid(w),
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
    limit_date = _payroll_start(w)
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
    computed fresh from attendance, never stored - same philosophy as a project's own Materials used or Daily
    wages (app/projects.py). For a salaried employee it is every month's salary after absences, plus house rent / petrol."""
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
            months = max(0, _months_elapsed(_payroll_start(w), today))
            earned = float(_salaried_earned(w, today, data_until_end))
            paid = float(w.paid_amount)
            # Every advance instalment due up to this month, counted in full like the month's salary (kohal, 2026-11-06).
            deduction = float(deduction_to_date(w, today))
            rows.append({
                "id": w.id, "name": w.name, "employment_type": w.employment_type, "wage_amount": wage,
                "months": months, "days": None, "period_start": None, "period_end": None, "period_label": None,
                "earned": earned, "paid": paid, "advance_deduction": deduction, "outstanding": round(earned - paid - deduction, 2),
                "last_paid": _last_paid(w),
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
        too_early = d < payroll_start
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


# ---------- the monthly payment sheet (kohal, 2026-11-08) ----------

SHEET_COLUMNS = [
    "Sr. No.", "Name", "From", "To", "Salary", "Total days of month", "Salary per day", "Present days in month", "Absent days",
    "Sick leave", "Casual leave", "Sick leave balance", "Casual leave balance", "Deduction", "Month net salary", "House rent / petrol", "Old adv bal", "Advance taken", "Total adv due", "Advance deduction",
    "Advance balance", "Salary due", "Gross salary", "Paid",
]


def _month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _paid_for_month(w, first: date, last: date) -> Decimal:
    """Salary paid for this month: payments marked as for it, plus any not marked for a month that were paid during it."""
    return sum((p.amount for p in w.payments if p.paid_date is not None and (
        p.period_start == first or (p.period_start is None and first <= p.paid_date <= last))), Decimal("0"))


def _advance_columns(w, first: date, last: date) -> dict:
    """The sheet's advance columns for one month: what was still owed from before it, what was taken in it, what comes off the
    month's salary, and what is left after."""
    given_before = sum((a.amount for a in w.advances if a.given_date < first), Decimal("0"))
    taken_back_before = sum((amt for a in w.advances for m, amt in instalments(a) if m < first), Decimal("0"))
    old = given_before - taken_back_before
    taken = sum((a.amount for a in w.advances if first <= a.given_date <= last), Decimal("0"))
    deduction = month_deduction(w, first.year, first.month)
    return {"old": old, "taken": taken, "total": old + taken, "deduction": deduction, "balance": old + taken - deduction}


def payment_sheet(year: int, month: int) -> dict:
    """Every salaried employee's row of the month's payment sheet (SHEET_COLUMNS), in name order."""
    _, data_until = _period()
    today = today_local()
    data_until_end = min(today, data_until) if data_until else None
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    rows = []
    counted_until, in_progress = None, False
    workers = Worker.query.filter_by(employment_type="regular").filter(Worker.wage_amount.isnot(None)).order_by(Worker.name).all()
    for w in workers:
        m = salaried_month(w, year, month, data_until_end)
        if m is None:
            continue
        adv = _advance_columns(w, first, last)
        leave = month_tally(w, first, last)
        left = leave_balance(w, last, used_until=last)
        gross = m["net"] + m["allowance"] - adv["deduction"]
        paid = _paid_for_month(w, first, last)
        if not m["complete"]:
            counted_until = m["counted_until"]
            in_progress = True
        rows.append({
            "id": w.id, "name": w.name, "from": m["from"].isoformat(), "to": m["to"].isoformat(),
            "salary": float(m["salary"]), "days_in_month": m["days_in_month"], "per_day": float(m["per_day"]),
            "present": m["present"], "absent": m["absent"], "sick_leave": leave["sick"], "casual_leave": leave["casual"],
            "unpaid_leave": leave["unpaid"], "sick_balance": round(left["sick"]["balance"], 1),
            "casual_balance": round(left["casual"]["balance"], 1), "deduction": float(m["cut"]), "net": float(m["net"]),
            "allowance": float(m["allowance"]), "old_advance": float(adv["old"]), "advance_taken": float(adv["taken"]),
            "advance_total": float(adv["total"]), "advance_deduction": float(adv["deduction"]), "advance_balance": float(adv["balance"]),
            "salary_due": float(gross - paid), "gross": float(gross), "paid": float(paid), "no_attendance": m["no_attendance"],
        })
    money_keys = ("salary", "deduction", "net", "allowance", "old_advance", "advance_taken", "advance_total", "advance_deduction",
                  "advance_balance", "salary_due", "gross", "paid")
    totals = {k: round(sum(r[k] for r in rows), 2) for k in money_keys}
    return {"month": _month_key(first), "label": first.strftime("%B %Y"), "rows": rows, "totals": totals,
            "in_progress": in_progress, "counted_until": counted_until.isoformat() if counted_until else None}


def _sheet_months(today: date) -> list:
    """Every month payroll covers, newest first."""
    months, month = [], today.replace(day=1)
    while month >= PAYROLL_START:
        months.append({"value": _month_key(month), "label": month.strftime("%B %Y")})
        month = add_months(month, -1)
    return months


def _sheet_month_arg(today: date):
    raw = request.args.get("month") or _month_key(today)
    try:
        year, month = (int(x) for x in raw.split("-"))
        first = date(year, month, 1)
    except ValueError:
        abort(422, "Give the month as YYYY-MM")
    if first < PAYROLL_START or first > today.replace(day=1):
        abort(422, "Pick a month payroll covers")
    return year, month


@bp.get("/api/payroll/sheet")
def sheet():
    today = today_local()
    year, month = _sheet_month_arg(today)
    return jsonify(**payment_sheet(year, month), months=_sheet_months(today), currency=settings_for_client()["currency"])


def sheet_workbook(data: dict) -> list:
    """The payment sheet as one Excel sheet, laid out like kohal's own: a title row, a two-row header (Work Days split into
    From / To), one boxed row per employee and a totals row."""
    n = len(SHEET_COLUMNS)
    title = [f"PAYMENT SHEET OF {data['label']}"]
    head = [c if c not in ("From", "To") else None for c in SHEET_COLUMNS]
    head[2] = "Work Days"
    sub = [None] * n
    sub[2], sub[3] = "From", "To"
    body = []
    for i, r in enumerate(data["rows"], start=1):
        body.append([i, r["name"], date.fromisoformat(r["from"]), date.fromisoformat(r["to"]), r["salary"], r["days_in_month"],
                     r["per_day"], r["present"], r["absent"], r["sick_leave"], r["casual_leave"], r["sick_balance"],
                     r["casual_balance"], r["deduction"], r["net"], r["allowance"], r["old_advance"],
                     r["advance_taken"], r["advance_total"], r["advance_deduction"], r["advance_balance"], r["salary_due"],
                     r["gross"], r["paid"]])
    t = data["totals"]
    total = [None, "Total", None, None, t["salary"], None, None, None, None, None, None, None, None, t["deduction"], t["net"], t["allowance"],
             t["old_advance"], t["advance_taken"], t["advance_total"], t["advance_deduction"], t["advance_balance"],
             t["salary_due"], t["gross"], t["paid"]]
    last_col = _col(n - 1)
    merges = [f"A1:{last_col}1", "C2:D2"] + [f"{_col(c)}2:{_col(c)}3" for c in range(n) if c not in (2, 3)]
    rows = [title, head, sub] + body + [total]
    styles = {0: "title", 1: "header", 2: "header", len(rows) - 1: "box_bold"}
    styles.update({3 + i: "box" for i in range(len(body))})
    widths = {0: 7, 1: 22, 2: 12, 3: 12}
    widths.update({c: 11 for c in range(4, n)})
    return [{"name": data["label"], "rows": rows, "row_styles": styles, "box_cols": n, "merges": merges, "widths": widths}]


@bp.get("/api/payroll/sheet.xlsx")
def sheet_xlsx():
    today = today_local()
    year, month = _sheet_month_arg(today)
    data = payment_sheet(year, month)
    return Response(build_workbook(sheet_workbook(data)),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="payment-sheet-{year}-{month:02d}.xlsx"',
                             "Cache-Control": "no-store"})


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

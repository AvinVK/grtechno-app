"""Leave for salaried employees (kohal, 2026-11-08: "now there are 6 sick leaves and 12 casual leaves for salaried employees. this
tally should be shown to the employees as well and to admin during payroll calc ... during attendance, there should be a tab of
applying for any kind of leave and the request should goto admin, once approved, it should be deducted and employee should be
considered on that leave").

The rules, as kohal answered them:
  - Leave builds up monthly: each month adds 0.5 sick and 1 casual (6 and 12 a year). A month counts from its first day.
  - The leave year runs April to March. Unused sick leave carries forward into the next year; unused casual leave lapses.
  - Leave is asked for in whole working days; a Sunday inside the dates is a paid day off already, so it is never counted.
  - The admin approves or rejects. Approved days come off the balance. Days beyond the balance are the admin's decision: paid
    anyway, or unpaid (cut from the salary like an absence).
  - Nothing builds up before payroll started in the app (1 Oct 2026), or before the employee's joining month.

A day of approved paid leave counts as a paid day on the payroll (never absent); an unpaid leave day is cut like an absence. See
app/payroll.py's salaried_month, which reads paid_leave_days below."""

import math
from datetime import date, timedelta

from flask import Blueprint, abort, g, jsonify, request

from .extensions import db
from .models import LeaveRequest, Worker, utcnow
from .timeutil import today_local
from .validation import api_errors

bp = Blueprint("leaves", __name__)
api_errors(bp)

KINDS = {"sick": "Sick leave", "casual": "Casual leave"}
MONTHLY = {"sick": 0.5, "casual": 1.0}
CARRIES_FORWARD = {"sick"}
LEAVE_START = date(2026, 10, 1)          # = app/payroll.py's PAYROLL_START: nothing builds up before the app tracked pay
MAX_DAYS = 60


def year_start(d: date) -> date:
    """1 April of the leave year `d` falls in."""
    return date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def year_label(d: date) -> str:
    start = year_start(d)
    return f"{start.year}-{str(start.year + 1)[2:]}"


def _next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _accrual_start(worker) -> date:
    start = LEAVE_START
    if worker.joining_date and worker.joining_date.replace(day=1) > start:
        start = worker.joining_date.replace(day=1)
    return start


def _months(worker, first: date, last: date) -> int:
    """Months whose first day lies in [first, last] that count for this employee."""
    month = max(first.replace(day=1), _accrual_start(worker))
    if month < first:
        month = _next_month(month)
    n = 0
    while month <= last:
        n += 1
        month = _next_month(month)
    return n


def working_days(start: date, end: date) -> list:
    """Every day in [start, end] but Sundays."""
    out, d = [], start
    while d <= end:
        if d.weekday() != 6:
            out.append(d)
        d += timedelta(days=1)
    return out


def _used(worker, kind, first: date, last: date, used_until=None) -> int:
    """Days taken off the balance by approved leave starting in [first, last] (and on or before used_until, when given)."""
    total = 0
    for r in worker.leave_requests:
        if r.status == "approved" and r.kind == kind and first <= r.start_date <= last and (used_until is None or r.start_date <= used_until):
            total += r.deducted_days
    return total


def balance(worker, as_of: date, used_until=None) -> dict:
    """Leave built up through as_of's month, less what was used, for the leave year as_of falls in. Sick leave carries the
    previous years' leftover in. `used_until` limits the used days to leave starting by then (a past month's figures)."""
    current = year_start(as_of)
    out = {"year": year_label(as_of)}
    for kind in KINDS:
        carried = 0.0
        if kind in CARRIES_FORWARD:
            y = year_start(_accrual_start(worker))
            while y < current:
                y_end = date(y.year + 1, 3, 31)
                carried += MONTHLY[kind] * _months(worker, y, y_end) - _used(worker, kind, y, y_end)
                y = date(y.year + 1, 4, 1)
        earned = MONTHLY[kind] * _months(worker, current, as_of)
        used = _used(worker, kind, current, date(current.year + 1, 3, 31), used_until)
        out[kind] = {"carried": carried, "earned": earned, "used": used, "balance": carried + earned - used}
    return out


def paid_leave_days(worker, start: date, end: date) -> dict:
    """{day: (kind, paid)} for every approved leave day in [start, end]. Within one request the paid days (off the balance, or
    paid anyway) come first and any unpaid ones last."""
    days = {}
    for r in worker.leave_requests:
        if r.status != "approved" or r.end_date < start or r.start_date > end:
            continue
        paid = r.deducted_days + r.extra_paid_days
        for i, d in enumerate(working_days(r.start_date, r.end_date)):
            if start <= d <= end:
                days[d] = (r.kind, i < paid)
    return days


def month_tally(worker, first: date, last: date) -> dict:
    """Leave days in one month by kind, and how many of them were unpaid."""
    tally = {"sick": 0, "casual": 0, "unpaid": 0}
    for kind, paid in paid_leave_days(worker, first, last).values():
        tally[kind] += 1
        if not paid:
            tally["unpaid"] += 1
    return tally


def _own_worker():
    """The signed-in person's own salaried employee record, or None."""
    worker = Worker.query.filter_by(user_code=g.user.code).first()
    return worker if worker is not None and worker.employment_type == "regular" else None


def can_apply(user) -> bool:
    worker = Worker.query.filter_by(user_code=user.code).first()
    return worker is not None and worker.employment_type == "regular"


def _balance_dict(worker, as_of):
    b = balance(worker, as_of)
    return {"year": b["year"], **{k: {key: round(v, 1) for key, v in b[k].items()} for k in KINDS}}


def _request_dict(r, today):
    d = r.to_dict()
    if r.status == "pending":
        d["available"] = round(balance(r.worker, max(r.start_date, today))[r.kind]["balance"], 1)
    return d


# ---------- the employee's own side ----------

@bp.get("/api/leaves/me")
def my_leave():
    worker = _own_worker()
    if worker is None:
        abort(403, "Leave is for salaried employees.")
    today = today_local()
    requests = sorted(worker.leave_requests, key=lambda r: (r.start_date, r.id), reverse=True)
    return jsonify(balance=_balance_dict(worker, today), requests=[_request_dict(r, today) for r in requests[:40]], kinds=KINDS)


def _dates(payload, errors):
    try:
        start = date.fromisoformat(str(payload.get("start_date") or ""))
    except ValueError:
        start = None
        errors["start_date"] = "Pick the first day"
    try:
        end = date.fromisoformat(str(payload.get("end_date") or "")) if payload.get("end_date") else start
    except ValueError:
        end = None
        errors["end_date"] = "Pick the last day"
    return start, end


@bp.post("/api/leaves")
def apply_leave():
    worker = _own_worker()
    if worker is None:
        abort(403, "Leave is for salaried employees.")
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    errors = {}
    kind = payload.get("kind")
    if kind not in KINDS:
        errors["kind"] = "Choose sick or casual leave"
    start, end = _dates(payload, errors)
    reason = str(payload.get("reason") or "").strip()
    if len(reason) > 300:
        errors["reason"] = "Keep the reason under 300 characters"
    days = []
    if start and end:
        if end < start:
            errors["end_date"] = "The last day can't be before the first"
        elif start < LEAVE_START:
            errors["start_date"] = "Leave in the app starts from 1 Oct 2026"
        elif (end - start).days >= MAX_DAYS:
            errors["end_date"] = f"Ask for at most {MAX_DAYS} days at a time"
        elif year_start(start) != year_start(end):
            errors["end_date"] = "Keep it within one leave year (April to March) - ask for the rest separately"
        else:
            days = working_days(start, end)
            if not days:
                errors["end_date"] = "Those are all Sundays - nothing to ask for"
    if not errors:
        clash = [r for r in worker.leave_requests if r.status in ("pending", "approved") and r.start_date <= end and r.end_date >= start]
        if clash:
            errors["start_date"] = "You've already asked for leave on some of those days"
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    row = LeaveRequest(worker_id=worker.id, kind=kind, start_date=start, end_date=end, days=len(days), reason=reason,
                       requested_by_code=g.user.code)
    db.session.add(row)
    db.session.commit()
    return jsonify(request=_request_dict(row, today_local())), 201


@bp.post("/api/leaves/<int:leave_id>/cancel")
def cancel_leave(leave_id):
    row = db.session.get(LeaveRequest, leave_id)
    worker = _own_worker()
    if row is None or worker is None or row.worker_id != worker.id:
        abort(404)
    if row.status != "pending":
        abort(409, "Only a request still waiting for the admin can be withdrawn.")
    row.status = "cancelled"
    db.session.commit()
    return jsonify(request=row.to_dict())


# ---------- the admin's side ----------

def _admin_only():
    if not g.user.is_admin:
        abort(403, "Only the admin approves leave.")


@bp.get("/api/leaves/admin")
def admin_leave():
    _admin_only()
    today = today_local()
    pending = LeaveRequest.query.filter_by(status="pending").order_by(LeaveRequest.start_date, LeaveRequest.id).all()
    recent = (LeaveRequest.query.filter(LeaveRequest.status.in_(("approved", "rejected")))
              .order_by(LeaveRequest.decided_at.desc(), LeaveRequest.id.desc()).limit(30).all())
    first = today.replace(day=1)
    last = _next_month(first) - timedelta(days=1)
    people = []
    for w in Worker.query.filter_by(employment_type="regular").order_by(Worker.name).all():
        people.append({"id": w.id, "name": w.name, "balance": _balance_dict(w, today), "this_month": month_tally(w, first, last)})
    return jsonify(pending=[_request_dict(r, today) for r in pending], recent=[r.to_dict() for r in recent], people=people,
                   year=year_label(today), month=first.strftime("%B %Y"), kinds=KINDS)


@bp.post("/api/leaves/<int:leave_id>/approve")
def approve_leave(leave_id):
    """Approve: days come off the balance up to what is there. Days beyond it need the admin's call - "paid" or "unpaid"."""
    _admin_only()
    row = db.session.get(LeaveRequest, leave_id)
    if row is None:
        abort(404)
    if row.status != "pending":
        abort(409, "This one has already been dealt with.")
    payload = request.get_json(silent=True) or {}
    available = balance(row.worker, max(row.start_date, today_local()))[row.kind]["balance"]
    deducted = max(0, min(row.days, math.floor(available)))
    extra = row.days - deducted
    if extra:
        choice = payload.get("extra")
        if choice not in ("paid", "unpaid"):
            return jsonify(error=f"{extra} day{'s' if extra != 1 else ''} beyond the balance - choose paid or unpaid",
                           fields={"extra": "Choose paid or unpaid"}, extra_days=extra), 422
        row.extra_paid_days, row.unpaid_days = (extra, 0) if choice == "paid" else (0, extra)
    row.deducted_days = deducted
    row.status = "approved"
    row.decided_by_code = g.user.code
    row.decided_at = utcnow()
    row.decision_note = str(payload.get("note") or "").strip()[:300]
    db.session.commit()
    return jsonify(request=row.to_dict())


@bp.post("/api/leaves/<int:leave_id>/reject")
def reject_leave(leave_id):
    _admin_only()
    row = db.session.get(LeaveRequest, leave_id)
    if row is None:
        abort(404)
    if row.status != "pending":
        abort(409, "This one has already been dealt with.")
    payload = request.get_json(silent=True) or {}
    row.status = "rejected"
    row.decided_by_code = g.user.code
    row.decided_at = utcnow()
    row.decision_note = str(payload.get("note") or "").strip()[:300]
    db.session.commit()
    return jsonify(request=row.to_dict())

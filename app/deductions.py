"""Pay deductions (kohal, 2026-11-09: "give deduction subtab below give advance. this deduction should be taken into consideration when
calculating salary for salaried or daily wages").

The admin puts an amount against one employee's pay with a note - a fine, damage, anything - for one pay period: a month for a
salaried employee, a 2-week period (1st-15th or 16th-end) for a daily-wage / contractor one. Payroll takes it off what the employee is
due (app/payroll.py reads the helpers below): the month's salary sheet, the day-rate sheet and the running dues all subtract it, next
to any advance being taken back.

Which periods can be picked (kohal, 2026-11-11: "in deduction of daily wages ... should show previous month's only and not all next
months ... dont touch salaried"): a salaried employee's deduction goes against this month or one of the next 11; a daily-wage /
contractor one's goes against wages already earned - last month's two pay periods and this month's so far, never a future one. The same
list is offered for an allowance (app/allowances.py).

Unlike an advance no money moves, so nothing shows in Accounts, and the admin can remove one given by mistake. Admin only."""

from datetime import date
from decimal import Decimal

from flask import Blueprint, abort, g, jsonify, request

from .advances import DAY_RATE_TYPES, add_months, prev_slot, slot_label, slot_start_of
from .extensions import db
from .models import PayDeduction, Worker, settings_for_client
from .modules import check_module
from .timeutil import today_local
from .validation import api_errors, parse_money
from .workers import EMPLOYMENT_TYPES

MONTHS_AHEAD = 12                       # a salaried employee: this month and the next 11
PERIOD_FLOOR = date(2026, 10, 1)        # = payroll's start: nothing is computed before it

bp = Blueprint("deductions", __name__)
api_errors(bp)


@bp.before_request
def _admin_only():
    check_module("workforce")
    if not g.user.is_admin:
        abort(403, "Only the admin can give or see deductions.")


def is_day_rate(worker) -> bool:
    return worker.employment_type in DAY_RATE_TYPES


def key(d: date, day_rate: bool) -> str:
    return d.isoformat() if day_rate else f"{d.year}-{d.month:02d}"


def label(d: date, day_rate: bool) -> str:
    return slot_label(d) if day_rate else d.strftime("%B %Y")


def period_choices(worker, today: date):
    """(the periods an adjustment can be put against, the one to start on). Daily wages: this month's pay periods so far and last
    month's, newest first, starting on the latest one that has ended; salaried: this month and the next 11."""
    if is_day_rate(worker):
        current = slot_start_of(today)
        first = max(add_months(today.replace(day=1), -1), PERIOD_FLOOR)
        periods, s = [], current
        while s >= first:
            periods.append(s)
            s = prev_slot(s)
        periods = periods or [current]
        return periods, periods[1] if len(periods) > 1 else periods[0]
    current = today.replace(day=1)
    return [add_months(current, i) for i in range(MONTHS_AHEAD)], current


def parse_period(worker, raw, today: date, errors: dict):
    """The period from the request, or None with errors["period"] set - it must be one period_choices offers."""
    periods, default = period_choices(worker, today)
    day_rate = is_day_rate(worker)
    text = str(raw or key(default, day_rate))
    try:
        if day_rate:
            period = date.fromisoformat(text)
        else:
            year, month = (int(x) for x in text.split("-"))
            period = date(year, month, 1)
    except ValueError:
        errors["period"] = "Pick the pay period" if day_rate else "Pick the month"
        return None
    if period not in periods:
        if day_rate:
            errors["period"] = "Pick this month's pay period or one from last month"
        else:
            errors["period"] = "That month has already passed" if period < periods[0] else "That is too far ahead"
        return None
    return period


def month_amount(worker, year: int, month: int) -> Decimal:
    """Deductions put against this employee's pay for one calendar month (a salaried employee's sheet)."""
    return sum((d.amount for d in worker.pay_deductions if (d.period_start.year, d.period_start.month) == (year, month)), Decimal("0"))


def slot_amount(worker, slot_start: date) -> Decimal:
    """Deductions put against one 2-week pay period (a day-rate employee's sheet)."""
    return sum((d.amount for d in worker.pay_deductions if d.period_start == slot_start), Decimal("0"))


def amount_to_date(worker, today: date) -> Decimal:
    """Every deduction for this month or an earlier one - a salaried employee's running total, counted in full the way the month's
    salary is."""
    cutoff = today.replace(day=1)
    return sum((d.amount for d in worker.pay_deductions if d.period_start <= cutoff), Decimal("0"))


def month_notes(worker, year: int, month: int) -> str:
    """What the deductions were for - their notes, for the slip."""
    return ", ".join(d.reason for d in worker.pay_deductions if (d.period_start.year, d.period_start.month) == (year, month))


def slot_notes(worker, slot_start: date) -> str:
    return ", ".join(d.reason for d in worker.pay_deductions if d.period_start == slot_start)


def deduction_dict(d, today: date) -> dict:
    day_rate = is_day_rate(d.worker)
    current = slot_start_of(today) if day_rate else today.replace(day=1)
    return {
        "id": d.id, "amount": float(d.amount), "reason": d.reason, "period": key(d.period_start, day_rate),
        "period_label": label(d.period_start, day_rate), "applied": d.period_start <= current,
        "created_by_name": d.created_by.name if d.created_by else None, "created_on": d.created_at.date().isoformat(),
    }


def _worker_or_404(raw) -> Worker:
    worker = db.session.get(Worker, raw) if isinstance(raw, int) else None
    if worker is None:
        abort(404, "Choose an employee from the list")
    return worker


@bp.get("/api/payroll/deductions")
def list_deductions():
    worker = _worker_or_404(request.args.get("worker_id", type=int))
    today = today_local()
    day_rate = is_day_rate(worker)
    periods, default = period_choices(worker, today)
    return jsonify(
        worker={"id": worker.id, "name": worker.name, "employment_type": worker.employment_type,
                "wage_amount": float(worker.wage_amount) if worker.wage_amount is not None else None},
        deductions=[deduction_dict(d, today) for d in sorted(worker.pay_deductions, key=lambda d: (d.period_start, d.id), reverse=True)],
        unit="fortnight" if day_rate else "month",
        periods=[{"value": key(p, day_rate), "label": label(p, day_rate)} for p in periods], current_period=key(default, day_rate),
        currency=settings_for_client()["currency"])


@bp.post("/api/payroll/deductions")
def give_deduction():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    today = today_local()
    errors = {}
    worker = _worker_or_404(payload.get("worker_id"))
    if worker.employment_type not in EMPLOYMENT_TYPES or worker.wage_amount is None:
        abort(422, "Set this employee's wage in Employee management first - a deduction comes off their pay.")
    amount = parse_money(payload.get("amount"), errors, "amount")
    if amount is not None and amount <= 0:
        errors["amount"] = "Enter the amount being deducted"
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        errors["reason"] = "Say what the deduction is for"
    elif len(reason) > 300:
        errors["reason"] = "Keep the note under 300 characters"
    period = parse_period(worker, payload.get("period"), today, errors)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    d = PayDeduction(worker_id=worker.id, amount=amount, period_start=period, reason=reason, created_by_code=g.user.code)
    db.session.add(d)
    db.session.commit()
    return jsonify(deduction=deduction_dict(d, today)), 201


@bp.delete("/api/payroll/deductions/<int:deduction_id>")
def remove_deduction(deduction_id: int):
    d = db.session.get(PayDeduction, deduction_id)
    if d is None:
        abort(404, "That deduction is already gone")
    db.session.delete(d)
    db.session.commit()
    return jsonify(ok=True)

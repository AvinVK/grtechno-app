"""Pay deductions (kohal, 2026-11-09: "give deduction subtab below give advance. this deduction should be taken into consideration when
calculating salary for salaried or daily wages").

The admin puts an amount against one employee's pay with a reason - a fine, damage, anything - for one pay period: a month for a
salaried employee, a 2-week period (1st-15th or 16th-end) for a daily-wage / contractor one. Payroll takes it off what the employee is
due (app/payroll.py reads the helpers below): the month's salary sheet, the day-rate sheet and the running dues all subtract it, next
to any advance being taken back.

Unlike an advance no money moves, so nothing shows in Accounts, and the admin can remove one given by mistake. Admin only."""

from datetime import date
from decimal import Decimal

from flask import Blueprint, abort, g, jsonify, request

from .advances import DAY_RATE_TYPES, add_months, add_slots, slot_label, slot_start_of
from .extensions import db
from .models import PayDeduction, Worker, settings_for_client
from .modules import check_module
from .timeutil import today_local
from .validation import api_errors, parse_money
from .workers import EMPLOYMENT_TYPES

MAX_PERIODS_AHEAD = 12                  # months for a salaried employee, pay periods x2 for a day-rate one

bp = Blueprint("deductions", __name__)
api_errors(bp)


@bp.before_request
def _admin_only():
    check_module("workforce")
    if not g.user.is_admin:
        abort(403, "Only the admin can give or see deductions.")


def _is_day_rate(worker) -> bool:
    return worker.employment_type in DAY_RATE_TYPES


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


def _key(d: date, day_rate: bool) -> str:
    return d.isoformat() if day_rate else f"{d.year}-{d.month:02d}"


def _label(d: date, day_rate: bool) -> str:
    return slot_label(d) if day_rate else d.strftime("%B %Y")


def deduction_dict(d, today: date) -> dict:
    day_rate = _is_day_rate(d.worker)
    current = slot_start_of(today) if day_rate else today.replace(day=1)
    return {
        "id": d.id, "amount": float(d.amount), "reason": d.reason, "period": _key(d.period_start, day_rate),
        "period_label": _label(d.period_start, day_rate), "applied": d.period_start <= current,
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
    day_rate = _is_day_rate(worker)
    if day_rate:
        current = slot_start_of(today)
        periods = [add_slots(current, i) for i in range(MAX_PERIODS_AHEAD * 2)]
    else:
        current = today.replace(day=1)
        periods = [add_months(current, i) for i in range(MAX_PERIODS_AHEAD)]
    return jsonify(
        worker={"id": worker.id, "name": worker.name, "employment_type": worker.employment_type,
                "wage_amount": float(worker.wage_amount) if worker.wage_amount is not None else None},
        deductions=[deduction_dict(d, today) for d in sorted(worker.pay_deductions, key=lambda d: (d.period_start, d.id), reverse=True)],
        unit="fortnight" if day_rate else "month",
        periods=[{"value": _key(p, day_rate), "label": _label(p, day_rate)} for p in periods], current_period=_key(current, day_rate),
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
    day_rate = _is_day_rate(worker)
    amount = parse_money(payload.get("amount"), errors, "amount")
    if amount is not None and amount <= 0:
        errors["amount"] = "Enter the amount being deducted"
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        errors["reason"] = "Say what the deduction is for"
    elif len(reason) > 300:
        errors["reason"] = "Keep the reason under 300 characters"
    period = None
    raw = str(payload.get("period") or (slot_start_of(today).isoformat() if day_rate else f"{today.year}-{today.month:02d}"))
    try:
        if day_rate:
            period = date.fromisoformat(raw)
            if period.day not in (1, 16):
                raise ValueError
            if period < slot_start_of(today):
                errors["period"] = "That pay period has already passed"
            elif period > add_slots(slot_start_of(today), MAX_PERIODS_AHEAD * 2 - 1):
                errors["period"] = "That is too far ahead"
        else:
            year, month = (int(x) for x in raw.split("-"))
            period = date(year, month, 1)
            if period < today.replace(day=1):
                errors["period"] = "That month has already passed"
            elif period > add_months(today.replace(day=1), MAX_PERIODS_AHEAD - 1):
                errors["period"] = "That is too far ahead"
    except ValueError:
        period = None
        errors["period"] = "Pick the pay period" if day_rate else "Pick the month"
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

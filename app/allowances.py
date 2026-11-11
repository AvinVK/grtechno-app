"""Pay allowances (kohal, 2026-11-11: "add allowance as well. have a note in deduction, advance and allowance to specify which allowance it is
and also adjust this in payroll sheet").

The mirror of app/deductions.py, adding to pay instead of taking off it: the admin puts an amount and a note saying which allowance it is
(travel, mobile, a bonus...) against one employee's pay for one period - a month for a salaried employee, a 2-week pay period for a
daily-wage / contractor one, picked from the same periods a deduction can be (app/deductions.py's period_choices). Payroll adds it to
what the employee is due (app/payroll.py reads the helpers below): the month's salary sheet, the day-rate sheet and the running dues, next
to the fixed house rent / petrol and ahead of any advance or deduction taken off. No money moves here, so nothing shows in Accounts, and
the admin can remove one given by mistake. Admin only."""

from datetime import date
from decimal import Decimal

from flask import Blueprint, abort, g, jsonify, request

from .deductions import is_day_rate, key, label, parse_period, period_choices
from .advances import slot_start_of
from .extensions import db
from .models import PayAllowance, Worker, settings_for_client
from .modules import check_module
from .timeutil import today_local
from .validation import api_errors, parse_money
from .workers import EMPLOYMENT_TYPES

bp = Blueprint("allowances", __name__)
api_errors(bp)


@bp.before_request
def _admin_only():
    check_module("workforce")
    if not g.user.is_admin:
        abort(403, "Only the admin can give or see allowances.")


def month_amount(worker, year: int, month: int) -> Decimal:
    """Allowances put against this employee's pay for one calendar month (a salaried employee's sheet)."""
    return sum((a.amount for a in worker.pay_allowances if (a.period_start.year, a.period_start.month) == (year, month)), Decimal("0"))


def slot_amount(worker, slot_start: date) -> Decimal:
    """Allowances put against one 2-week pay period (a day-rate employee's sheet)."""
    return sum((a.amount for a in worker.pay_allowances if a.period_start == slot_start), Decimal("0"))


def amount_to_date(worker, today: date) -> Decimal:
    """Every allowance for this month or an earlier one - a salaried employee's running total, counted in full like the month's salary."""
    cutoff = today.replace(day=1)
    return sum((a.amount for a in worker.pay_allowances if a.period_start <= cutoff), Decimal("0"))


def month_notes(worker, year: int, month: int) -> str:
    """Which allowances they were - the notes of this month's, for the slip."""
    return ", ".join(a.note for a in worker.pay_allowances if (a.period_start.year, a.period_start.month) == (year, month))


def slot_notes(worker, slot_start: date) -> str:
    return ", ".join(a.note for a in worker.pay_allowances if a.period_start == slot_start)


def allowance_dict(a, today: date) -> dict:
    day_rate = is_day_rate(a.worker)
    current = slot_start_of(today) if day_rate else today.replace(day=1)
    return {
        "id": a.id, "amount": float(a.amount), "note": a.note, "period": key(a.period_start, day_rate),
        "period_label": label(a.period_start, day_rate), "applied": a.period_start <= current,
        "created_by_name": a.created_by.name if a.created_by else None, "created_on": a.created_at.date().isoformat(),
    }


def _worker_or_404(raw) -> Worker:
    worker = db.session.get(Worker, raw) if isinstance(raw, int) else None
    if worker is None:
        abort(404, "Choose an employee from the list")
    return worker


@bp.get("/api/payroll/allowances")
def list_allowances():
    worker = _worker_or_404(request.args.get("worker_id", type=int))
    today = today_local()
    day_rate = is_day_rate(worker)
    periods, default = period_choices(worker, today)
    return jsonify(
        worker={"id": worker.id, "name": worker.name, "employment_type": worker.employment_type,
                "wage_amount": float(worker.wage_amount) if worker.wage_amount is not None else None},
        allowances=[allowance_dict(a, today) for a in sorted(worker.pay_allowances, key=lambda a: (a.period_start, a.id), reverse=True)],
        unit="fortnight" if day_rate else "month",
        periods=[{"value": key(p, day_rate), "label": label(p, day_rate)} for p in periods], current_period=key(default, day_rate),
        currency=settings_for_client()["currency"])


@bp.post("/api/payroll/allowances")
def give_allowance():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    today = today_local()
    errors = {}
    worker = _worker_or_404(payload.get("worker_id"))
    if worker.employment_type not in EMPLOYMENT_TYPES or worker.wage_amount is None:
        abort(422, "Set this employee's wage in Employee management first - an allowance is added to their pay.")
    amount = parse_money(payload.get("amount"), errors, "amount")
    if amount is not None and amount <= 0:
        errors["amount"] = "Enter the allowance amount"
    note = str(payload.get("note") or "").strip()
    if not note:
        errors["note"] = "Say which allowance it is"
    elif len(note) > 300:
        errors["note"] = "Keep the note under 300 characters"
    period = parse_period(worker, payload.get("period"), today, errors)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    a = PayAllowance(worker_id=worker.id, amount=amount, period_start=period, note=note, created_by_code=g.user.code)
    db.session.add(a)
    db.session.commit()
    return jsonify(allowance=allowance_dict(a, today)), 201


@bp.delete("/api/payroll/allowances/<int:allowance_id>")
def remove_allowance(allowance_id: int):
    a = db.session.get(PayAllowance, allowance_id)
    if a is None:
        abort(404, "That allowance is already gone")
    db.session.delete(a)
    db.session.commit()
    return jsonify(ok=True)

"""Advance salary (kohal, 2026-11-06: "advance salary feature. this is applicable for both daily wages and salaried. admin should be able
to allocate full or part advance salary to any employee and the deduction can be selected in parts across future salaries. like say if
20k is selected as advance it should then show across how many months it will be deducted if selected 4 months then next 4 months, 5k
from each month's salary will be deducted").

The admin gives an employee money ahead of pay, through one of the payment accounts, and picks how many months to take it back over.
The amount is split evenly across those months (a rupee-and-paise remainder lands on the last one), starting from a month the admin
chooses - the month after the advance unless they say otherwise. What is taken each month comes off what the employee is due:

  - a salaried employee: the month's instalment comes off that month's salary;
  - a daily-wage or contractor employee: the month's instalment is split across that month's two pay periods (1st-15th, 16th-end).

Nothing here is ever paid out twice: the advance itself leaves the account once, when it is given (it is a debit on that account's
Accounts ledger), and each instalment only reduces what the employee is still owed in Payroll (app/payroll.py reads the helpers
below). An advance is never edited or deleted from the app once given - it is money that has already moved.

Admin only to give or look at; the deduction figures themselves show wherever Payroll shows a due."""

from datetime import date
from decimal import Decimal

from flask import Blueprint, abort, g, jsonify, request

from .constants import PAYMENT_ACCOUNTS
from .extensions import db
from .models import SalaryAdvance, Worker, settings_for_client
from .modules import check_module
from .timeutil import today_local
from .validation import api_errors, parse_money
from .workers import EMPLOYMENT_TYPES

MAX_MONTHS = 24

bp = Blueprint("advances", __name__)
api_errors(bp)


@bp.before_request
def _admin_only():
    check_module("workforce")
    if not g.user.is_admin:
        abort(403, "Only the admin can give or see salary advances.")


def add_months(first: date, n: int) -> date:
    """The first of the month n months after `first`'s month."""
    index = first.year * 12 + (first.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)


def instalments(advance):
    """[(first of month, amount)] - the advance split evenly across its months, the last one taking any leftover paise."""
    base = (advance.amount / advance.months).quantize(Decimal("0.01"))
    return [(add_months(advance.first_month, i), base if i < advance.months - 1 else advance.amount - base * (advance.months - 1))
            for i in range(advance.months)]


def month_deduction(worker, year: int, month: int) -> Decimal:
    """Everything being taken back from this employee's pay for one calendar month."""
    total = Decimal("0")
    for adv in worker.advances:
        for m, amt in instalments(adv):
            if (m.year, m.month) == (year, month):
                total += amt
    return total


def deduction_to_date(worker, today: date) -> Decimal:
    """Every instalment due up to and including today's month - the salaried running total (the current month counts in full, the
    same way a month's salary does)."""
    cutoff = today.replace(day=1)
    return sum((amt for adv in worker.advances for m, amt in instalments(adv) if m <= cutoff), Decimal("0"))


def slot_deduction(worker, slot_start: date) -> Decimal:
    """The share of the month's instalment that comes off one pay period: half in the 1st-15th, the rest in the 16th-end."""
    month = month_deduction(worker, slot_start.year, slot_start.month)
    first_half = (month / 2).quantize(Decimal("0.01"))
    return first_half if slot_start.day == 1 else month - first_half


def _month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def advance_dict(adv, today: date) -> dict:
    rows = instalments(adv)
    cutoff = today.replace(day=1)
    deducted = sum((amt for m, amt in rows if m <= cutoff), Decimal("0"))
    return {
        "id": adv.id, "amount": float(adv.amount), "months": adv.months, "monthly": float(rows[0][1]),
        "first_month": _month_key(adv.first_month), "given_date": adv.given_date.isoformat(), "payment_account": adv.payment_account,
        "note": adv.note, "created_by_name": adv.created_by.name if adv.created_by else None,
        "deducted": float(deducted), "remaining": float(adv.amount - deducted),
        "instalments": [{"month": _month_key(m), "amount": float(amt), "status": "deducted" if m < cutoff else "this month" if m == cutoff else "upcoming"}
                        for m, amt in rows],
    }


def _worker_or_404(raw) -> Worker:
    worker = db.session.get(Worker, raw) if isinstance(raw, int) else None
    if worker is None:
        abort(404, "Choose an employee from the list")
    return worker


@bp.get("/api/payroll/advances")
def list_advances():
    worker = _worker_or_404(request.args.get("worker_id", type=int))
    today = today_local()
    return jsonify(
        worker={"id": worker.id, "name": worker.name, "employment_type": worker.employment_type,
                "wage_amount": float(worker.wage_amount) if worker.wage_amount is not None else None},
        advances=[advance_dict(a, today) for a in sorted(worker.advances, key=lambda a: (a.given_date, a.id), reverse=True)],
        accounts=PAYMENT_ACCOUNTS, current_month=_month_key(today), next_month=_month_key(add_months(today, 1)), max_months=MAX_MONTHS,
        currency=settings_for_client()["currency"])


@bp.post("/api/payroll/advances")
def give_advance():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    today = today_local()
    errors = {}
    worker = db.session.get(Worker, payload.get("worker_id")) if isinstance(payload.get("worker_id"), int) else None
    if worker is None:
        abort(404, "Choose an employee from the list")
    if worker.employment_type not in EMPLOYMENT_TYPES or worker.wage_amount is None:
        abort(422, "Set this employee's wage in Employee management first - an advance is taken back from their pay.")
    amount = parse_money(payload.get("amount"), errors, "amount")
    if amount is not None and amount <= 0:
        errors["amount"] = "Enter the amount being given"
    months = payload.get("months")
    if not isinstance(months, int) or isinstance(months, bool) or not 1 <= months <= MAX_MONTHS:
        errors["months"] = f"Choose between 1 and {MAX_MONTHS} months"
    try:
        year, month = (int(x) for x in str(payload.get("first_month") or _month_key(add_months(today, 1))).split("-"))
        first_month = date(year, month, 1)
        if first_month < today.replace(day=1):
            errors["first_month"] = "Deductions can't start in a month that has already passed"
    except ValueError:
        first_month = None
        errors["first_month"] = "Pick the month deductions start"
    account = payload.get("payment_account")
    if account not in PAYMENT_ACCOUNTS:
        errors["payment_account"] = "Choose the account it is paid from"
    note = str(payload.get("note") or "").strip()
    if len(note) > 300:
        errors["note"] = "Keep the note under 300 characters"
    try:
        given = date.fromisoformat(payload["given_date"]) if payload.get("given_date") else today
        if given > today:
            errors["given_date"] = "That day hasn't happened yet"
    except ValueError:
        given = None
        errors["given_date"] = "Pick the day"
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    adv = SalaryAdvance(worker_id=worker.id, amount=amount, months=months, first_month=first_month, given_date=given,
                        payment_account=account, note=note, created_by_code=g.user.code)
    db.session.add(adv)
    db.session.commit()
    return jsonify(advance=advance_dict(adv, today)), 201

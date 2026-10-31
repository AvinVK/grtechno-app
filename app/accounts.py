"""Accounts (kohal, 2026-10-31: "for admin, i want Accounts block in me tab. it should have all the bank accounts,
and when clicking on one, it should show the debits and credits and who requested it, when it happened and what
was the reason (fooding, petrol, salary, wages etc)").

Admin only. There is no ledger table of its own: every place that records money already says which account it went
through (constants.PAYMENT_ACCOUNTS), so this page reads them all and lines them up -

  Credits (money in):  project payments received, lead advances.
  Debits (money out):  salary and wages paid, fooding allotted, cash handed to an employee for purchases, petrol
                       paid out, inventory bought for cash.

Left out on purpose, because the money already left through one of the above: an employee's own fooding expense
and what they buy with the cash they were handed. Entries made before the account list existed carry an older
mode ("Cash", "UPI"...) and belong to no account, so they are not here."""

from datetime import datetime
from decimal import Decimal

from flask import Blueprint, abort, g, jsonify, render_template, request

from .constants import PAYMENT_ACCOUNTS
from .models import (
    CashTopup, FoodingEntry, Lead, MaterialMovement, PetrolEntry, ProjectPayment, User, WorkerPayment, settings_for_client,
)
from .validation import api_errors

bp = Blueprint("accounts", __name__)
api_errors(bp)


@bp.before_request
def _admin_only():
    if not g.user.is_admin:
        abort(403, "Only the admin can see the accounts.")


def _day(value):
    if value is None:
        return None
    return (value.date() if isinstance(value, datetime) else value).isoformat()


def _name(code):
    user = User.query.get(code) if code else None
    return user.name if user else None


def _row(kind, when, amount, reason, party, detail="", requested_by=None, approved_by=None):
    return {"kind": kind, "date": _day(when), "amount": float(amount), "reason": reason, "party": party,
            "detail": detail, "requested_by": requested_by, "approved_by": approved_by}


def _worker_reason(worker):
    return "Wages" if worker.employment_type in ("daily_wages", "contractor") else "Salary"


def ledger(account):
    """Every debit and credit that went through `account`, newest first."""
    rows = []

    for p in ProjectPayment.query.filter(ProjectPayment.mode == account, ProjectPayment.paid_date.isnot(None)).all():
        rows.append(_row("credit", p.paid_date, p.amount, "Project payment", p.project.client.name,
                         f"{p.project.code} · {p.label}"))
    for lead in Lead.query.filter(Lead.advance_mode == account, Lead.advance_amount.isnot(None), Lead.advance_date.isnot(None)).all():
        rows.append(_row("credit", lead.advance_date, lead.advance_amount, "Lead advance",
                         lead.company or lead.contact_name, lead.contact_name if lead.company else ""))

    for p in WorkerPayment.query.filter(WorkerPayment.mode == account, WorkerPayment.paid_date.isnot(None)).all():
        rows.append(_row("debit", p.paid_date, p.amount, _worker_reason(p.worker), p.worker.name, p.label))
    for e in FoodingEntry.query.filter_by(kind="allot", status="approved", payment_mode=account).all():
        rows.append(_row("debit", e.entry_date, e.amount, "Fooding", e.account.worker.name,
                         requested_by=e.created_by.name if e.created_by else None, approved_by=_name(e.decided_by_code)))
    for t in CashTopup.query.filter_by(payment_mode=account).all():
        rows.append(_row("debit", t.entry_date, t.amount, "Cash given for purchases", t.account.worker.name, t.note,
                         requested_by=t.created_by.name if t.created_by else None))
    for e in PetrolEntry.query.filter_by(cash_status="paid", cash_mode=account).all():
        rows.append(_row("debit", e.cash_decided_at or e.work_date, e.amount or Decimal("0"), "Petrol", e.user.name if e.user else "",
                         f"Ride of {e.work_date.strftime('%d %b %Y')}", requested_by=e.user.name if e.user else None,
                         approved_by=_name(e.cash_decided_by_code)))
    for m in MaterialMovement.query.filter_by(kind="in", status="approved", payment_mode="cash", payment_account=account).all():
        rows.append(_row("debit", m.entry_date, m.total_cost or m.amount, "Inventory purchase",
                         m.supplier.name if m.supplier else "", m.material.name,
                         requested_by=m.created_by.name if m.created_by else None, approved_by=_name(m.approved_by_code)))

    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows


def _totals(rows):
    credit = sum(r["amount"] for r in rows if r["kind"] == "credit")
    debit = sum(r["amount"] for r in rows if r["kind"] == "debit")
    return {"credits": round(credit, 2), "debits": round(debit, 2), "balance": round(credit - debit, 2), "count": len(rows)}


@bp.get("/accounts")
def page():
    return render_template("accounts.html")


@bp.get("/api/accounts")
def list_accounts():
    return jsonify(accounts=[{"name": a, **_totals(ledger(a))} for a in PAYMENT_ACCOUNTS],
                   currency=settings_for_client()["currency"])


@bp.get("/api/accounts/detail")
def account_detail():
    name = request.args.get("name", "")
    if name not in PAYMENT_ACCOUNTS:
        abort(404)
    rows = ledger(name)
    return jsonify(name=name, **_totals(rows), entries=rows, currency=settings_for_client()["currency"])

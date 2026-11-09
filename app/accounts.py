"""Accounts (kohal, 2026-10-31: "for admin, i want Accounts block in me tab. it should have all the bank accounts,
and when clicking on one, it should show the debits and credits and who requested it, when it happened and what
was the reason (fooding, petrol, salary, wages etc)").

Admin only. There is no ledger table of its own: every place that records money already says which account it went
through (constants.PAYMENT_ACCOUNTS), so this page reads them all and lines them up -

  Credits (money in):  project payments received, lead advances, self transfers in.
  Debits (money out):  salary and wages paid, salary advances given, commission paid (each part), fooding allotted, cash handed to an employee for purchases, petrol
                       paid out, inventory bought for cash, what the admin bought directly (admin purchases), payments made to
                       suppliers, self transfers out.

An account can have an opening balance and date (AccountOpening): entries dated before that day are left out, and the balance is
the opening amount plus what came in, less what went out, from that day on (the day itself counts).

Left out on purpose, because the money already left through one of the above: an employee's own fooding expense
and what they buy with the cash they were handed. Entries made before the account list existed carry an older
mode ("Cash", "UPI"...) and belong to no account, so they are not here."""

from datetime import datetime
from decimal import Decimal

from flask import Blueprint, abort, g, jsonify, render_template, request

from .constants import PAYMENT_ACCOUNTS
from .extensions import db
from .models import (
    AccountOpening, AccountTransfer, AdminPurchase, CommissionPayment, CashTopup, PetrolPayout, SalaryAdvance, SupplierPayment, FoodingEntry, Lead, MaterialMovement, PetrolEntry, ProjectPayment, User, WorkerPayment, settings_for_client,
)
from .timeutil import today_local
from .validation import Fields, api_errors, parse_money

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


def _row(kind, when, amount, reason, party, detail="", requested_by=None, approved_by=None, transfer_id=None):
    return {"kind": kind, "date": _day(when), "amount": float(amount), "reason": reason, "party": party,
            "detail": detail, "requested_by": requested_by, "approved_by": approved_by, "transfer_id": transfer_id}


def _worker_reason(worker):
    return "Wages" if worker.employment_type in ("daily_wages", "contractor") else "Salary"


def opening_for(account):
    return AccountOpening.query.filter_by(account=account).first()


def _opening_dict(opening):
    return {"amount": float(opening.amount), "date": opening.as_of.isoformat()} if opening else None


def ledger(account, opening=None):
    """Every debit and credit that went through `account`, newest first - from the opening date on, when it has one."""
    rows = _all_rows(account)
    if opening is not None:
        since = opening.as_of.isoformat()
        rows = [r for r in rows if r["date"] is None or r["date"] >= since]
    return rows


def _all_rows(account):
    rows = []

    for p in ProjectPayment.query.filter(ProjectPayment.mode == account, ProjectPayment.paid_date.isnot(None)).all():
        rows.append(_row("credit", p.paid_date, p.amount, "Project payment", p.project.client.name,
                         f"{p.project.code} · {p.label}"))
    for lead in Lead.query.filter(Lead.advance_mode == account, Lead.advance_amount.isnot(None), Lead.advance_date.isnot(None)).all():
        rows.append(_row("credit", lead.advance_date, lead.advance_amount, "Lead advance",
                         lead.company or lead.contact_name, lead.contact_name if lead.company else ""))

    for p in WorkerPayment.query.filter(WorkerPayment.mode == account, WorkerPayment.paid_date.isnot(None)).all():
        rows.append(_row("debit", p.paid_date, p.amount, _worker_reason(p.worker), p.worker.name, p.label))
    for a in SalaryAdvance.query.filter_by(payment_account=account).all():
        rows.append(_row("debit", a.given_date, a.amount, "Salary advance", a.worker.name, f"Taken back over {a.months} {'pay period' if a.unit == 'fortnight' else 'month'}{'s' if a.months != 1 else ''}",
                         requested_by=a.created_by.name if a.created_by else None))
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
    for o in PetrolPayout.query.filter_by(status="paid", payment_account=account).all():
        rows.append(_row("debit", o.decided_at, o.amount_paid or Decimal("0"), "Petrol", o.user.name if o.user else "", "Petrol payment",
                         requested_by=o.user.name if o.user else None, approved_by=_name(o.decided_by_code)))
    for m in MaterialMovement.query.filter_by(kind="in", status="approved", payment_mode="cash", payment_account=account).all():
        rows.append(_row("debit", m.entry_date, m.total_cost or m.amount, "Inventory purchase",
                         m.supplier.name if m.supplier else "", m.material.name,
                         requested_by=m.created_by.name if m.created_by else None, approved_by=_name(m.approved_by_code)))

    for p in AdminPurchase.query.filter_by(payment_account=account).all():
        rows.append(_row("debit", p.entry_date, p.amount, "Material purchase" if p.category == "material" else (p.expense_head or "Other expense"),
                         p.supplier, p.material_name, requested_by=p.created_by.name if p.created_by else None))

    for c in CommissionPayment.query.filter_by(payment_account=account).all():
        e = c.expense
        rows.append(_row("debit", c.paid_date, c.amount, "Commission", e.given_to, f"{e.project.code} · {e.project.title}",
                         requested_by=c.created_by.name if c.created_by else None))

    for p in SupplierPayment.query.filter_by(payment_account=account).all():
        rows.append(_row("debit", p.entry_date, p.amount, "Supplier payment", p.supplier.name, f"{p.mode}{' · ' + p.note if p.note else ''}",
                         requested_by=p.created_by.name if p.created_by else None))

    # Self transfers: the same row is the debit of the account it left and the credit of the one it reached.
    for t in AccountTransfer.query.filter((AccountTransfer.from_account == account) | (AccountTransfer.to_account == account)).all():
        out = t.from_account == account
        rows.append(_row("debit" if out else "credit", t.entry_date, t.amount, "Self transfer",
                         t.to_account if out else t.from_account, t.note,
                         requested_by=t.created_by.name if t.created_by else None, transfer_id=t.id))

    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows


def _totals(rows, opening=None):
    credit = sum(r["amount"] for r in rows if r["kind"] == "credit")
    debit = sum(r["amount"] for r in rows if r["kind"] == "debit")
    start = float(opening.amount) if opening else 0.0
    return {"credits": round(credit, 2), "debits": round(debit, 2), "balance": round(start + credit - debit, 2), "count": len(rows),
            "opening": _opening_dict(opening)}


def _balance(account):
    opening = opening_for(account)
    return _totals(ledger(account, opening), opening)["balance"]


@bp.get("/accounts")
def page():
    return render_template("accounts.html")


@bp.get("/api/accounts")
def list_accounts():
    openings = {o.account: o for o in AccountOpening.query.all()}
    return jsonify(accounts=[{"name": a, **_totals(ledger(a, openings.get(a)), openings.get(a))} for a in PAYMENT_ACCOUNTS],
                   currency=settings_for_client()["currency"])


@bp.get("/api/accounts/detail")
def account_detail():
    name = request.args.get("name", "")
    if name not in PAYMENT_ACCOUNTS:
        abort(404)
    opening = opening_for(name)
    rows = ledger(name, opening)
    return jsonify(name=name, **_totals(rows, opening), entries=rows, account_names=PAYMENT_ACCOUNTS,
                   currency=settings_for_client()["currency"])


@bp.put("/api/accounts/opening")
def set_opening():
    """Set (or change) what an account held on a day. Nothing is deleted - entries before that day are only left out of the view."""
    payload = request.get_json(silent=True) or {}
    f = Fields(payload)
    f.choice("name", PAYMENT_ACCOUNTS)
    f.date("as_of")
    if f.errors.get("name") or "name" not in f.data:
        abort(404)
    amount = parse_money(payload.get("amount"), f.errors) if payload.get("amount") not in (None, "") else None
    if amount is None and "amount" not in f.errors:
        f.errors["amount"] = "Enter the opening balance (0 if it was empty)"
    if not f.data.get("as_of") and "as_of" not in f.errors:
        f.errors["as_of"] = "Pick the day this balance was true"
    elif f.data.get("as_of") and f.data["as_of"] > today_local():
        f.errors["as_of"] = "That day hasn't happened yet"
    if f.errors:
        return jsonify(error="Check the highlighted fields.", fields=f.errors), 422
    opening = opening_for(f.data["name"]) or AccountOpening(account=f.data["name"])
    opening.amount, opening.as_of, opening.updated_by_code = amount, f.data["as_of"], g.user.code
    db.session.add(opening)
    db.session.commit()
    return jsonify(ok=True, opening=_opening_dict(opening))


@bp.post("/api/accounts/transfers")
def add_transfer():
    payload = request.get_json(silent=True) or {}
    f = Fields(payload)
    f.choice("from_account", PAYMENT_ACCOUNTS)
    f.choice("to_account", PAYMENT_ACCOUNTS)
    f.date("entry_date")
    f.text("note", 200)
    for name, label in (("from_account", "Choose the account to take it from"), ("to_account", "Choose the account to put it in")):
        if name not in f.data and name not in f.errors:
            f.errors[name] = label
        elif f.errors.get(name):
            f.errors[name] = label
    amount = parse_money(payload.get("amount"), f.errors) if payload.get("amount") not in (None, "") else None
    if amount is None and "amount" not in f.errors:
        f.errors["amount"] = "Enter the amount"
    elif amount is not None and amount <= 0:
        f.errors["amount"] = "Enter an amount greater than 0"
    if not f.errors and f.data["from_account"] == f.data["to_account"]:
        f.errors["to_account"] = "Pick a different account to move it to"
    if not f.errors:
        have = Decimal(str(_balance(f.data["from_account"])))
        if amount > have:
            shown = f"{have:,.2f}".rstrip("0").rstrip(".")
            f.errors["amount"] = f"Only {settings_for_client()['currency']}{shown} in {f.data['from_account']}" if have > 0                 else f"There is no money in {f.data['from_account']}"
    if f.errors:
        return jsonify(error="Check the highlighted fields.", fields=f.errors), 422
    t = AccountTransfer(from_account=f.data["from_account"], to_account=f.data["to_account"], amount=amount,
                        note=f.data.get("note", ""), entry_date=f.data.get("entry_date") or today_local(),
                        created_by_code=g.user.code)
    db.session.add(t)
    db.session.commit()
    return jsonify(ok=True, id=t.id), 201


@bp.delete("/api/accounts/transfers/<int:transfer_id>")
def delete_transfer(transfer_id):
    t = db.session.get(AccountTransfer, transfer_id)
    if t is None:
        abort(404)
    db.session.delete(t)
    db.session.commit()
    return jsonify(ok=True)

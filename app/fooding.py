"""Fooding: a food (and now any) allowance (kohal, 2026-10-18: "the admin or accountant will alot some
money to the daily wages employee. 200 rs per day should be deducted daily for food automatically unless
admin or accountant pauses that feature"; later the same day: "now there are salaried employees which can
be on 200rs fooding thing... a check mark... named 'fooding?'"). Not a module - nothing here is gated by
app/modules.py's check_module, since who may use it isn't a role-level thing (see auth.can_manage_fooding)
or depends on a personal HR detail (Worker.fooding_eligible) that cuts across roles, not a service every
role either has or doesn't.

Two audiences share one page, /fooding - same shape as /attendance's own team_only split (app/attendance.py):
- The admin or accountant allots money and pauses/resumes, for everyone fooding_eligible (kohal, 2026-10-18:
  "dude, fooding should open its own page!" - this used to only be a block on the Me hub, not a page).
- Someone fooding_eligible sees their own balance - allotted, remaining, and the ₹200/day note, or "Paused"
  - reached from a tile on their own Me hub, alongside /wages (see app/wages.py), which stays daily-wage
  only (a salaried person already has their own pay on file; it's only the fooding wallet they can opt
  onto, not day-rate tracking).

fooding_eligible is just Worker.fooding_opt_in now (kohal, 2026-10-18: "should be automatically on for
daily wages and off for others. their might be plans to remove the fooding option completely") - daily
wages only sets that checkbox's starting point in the Edit form (see people.js), it's no longer baked into
eligibility here, so removing fooding later is just removing the field, not also untangling it from
employment_type. See migrations/versions/a3c7e1f9d548_fooding_opt_in_backfill.py for the one-time backfill
this needed so an already-eligible daily-wage worker didn't silently lose it when this shipped.

See FoodingAccount in app/models.py for how the running balance is kept current without a scheduled job."""

from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, g, jsonify, render_template, request

from .auth import can_manage_fooding
from .extensions import db
from .models import FoodingAccount, FoodingEntry, Worker, settings_for_client
from .timeutil import today_local
from .validation import api_errors

bp = Blueprint("fooding", __name__)
api_errors(bp)

# How fooding money changed hands (kohal, 2026-10-18: "add mode of payment option as well. shld be cash,
# online/UPI") - a fixed pair, not the general PAYMENT_MODES list (Cheque/Bank transfer/Other don't apply
# to handing cash or a UPI transfer to someone in person).
PAYMENT_MODES = ("Cash", "Online/UPI")


def _manage_only():
    if not can_manage_fooding(g.user):
        abort(403, "Only the admin or accountant can manage fooding.")


def own_worker():
    """The Worker row standing in for the signed-in person, if any - see auth.sync_worker_for_user. None
    for the admin, and for anyone who's never actually signed in to get one made."""
    return Worker.query.filter_by(user_code=g.user.code).first()


def _fooding_eligible_or_404(worker_id):
    worker = db.session.get(Worker, worker_id)
    if worker is None or not worker.fooding_eligible:
        abort(404)
    return worker


def _fooding_eligible_query():
    """Every Worker who belongs on the fooding wallet (Worker.fooding_eligible) - a query, not the Python
    property, since this drives a list."""
    return Worker.query.filter(Worker.fooding_opt_in.is_(True))


def account_for(worker, *, create=False):
    """This worker's fooding account, settled up to today (see FoodingAccount.settle) - None if they've
    never been allotted anything and `create` wasn't asked for. Caller still needs to commit."""
    account = worker.fooding_account
    if account is None:
        if not create:
            return None
        # Every field explicit, not left to the column defaults - those only apply at flush/INSERT, and
        # settle() right below (and the += in allot(), right after this returns) need real values before
        # this is ever flushed.
        account = FoodingAccount(worker=worker, anchor_date=date.today(),
                                  allotted_total=Decimal("0"), deducted_total=Decimal("0"), is_paused=False)
        db.session.add(account)
    account.settle()
    return account


def _empty_dict(worker):
    """Same shape as FoodingAccount.to_dict(), for a daily-wage worker nobody has allotted anything to
    yet - nothing to settle, so no need to actually create a row just to answer a GET."""
    return {
        "worker_id": worker.id, "worker_name": worker.name, "allotted_total": 0.0, "deducted_total": 0.0,
        "remaining": 0.0, "is_paused": False, "daily_amount": float(FoodingAccount.DAILY_AMOUNT),
    }


# ---------- the page itself, same split as /attendance's team_only ----------

@bp.get("/fooding")
def page():
    if can_manage_fooding(g.user):
        return render_template("fooding.html", page_title="Fooding", mode="manage")
    worker = own_worker()
    if worker is None or not worker.fooding_eligible:
        abort(403, "Fooding is only for daily-wage or fooding-eligible employees.")
    return render_template("fooding.html", page_title="Fooding", mode="own")


@bp.get("/api/fooding/me")
def my_fooding():
    worker = own_worker()
    if worker is None or not worker.fooding_eligible:
        abort(403, "Fooding is only for daily-wage or fooding-eligible employees.")
    account = account_for(worker)
    db.session.commit()
    return jsonify(fooding=account.to_dict() if account else _empty_dict(worker),
                   entries=[e.to_dict() for e in account.entries] if account else [],
                   payment_modes=list(PAYMENT_MODES),
                   currency=settings_for_client()["currency"])


def _amount_and_mode(payload, *, balance_cap=None):
    """amount (a positive Decimal, optionally capped at balance_cap - "only X remaining") and payment_mode
    (one of PAYMENT_MODES) from the request - shared by allot and the worker's own expense entry. Returns
    (amount, payment_mode, errors)."""
    errors = {}
    try:
        amount = Decimal(str(payload.get("amount")))
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    if amount is None or not amount.is_finite() or amount <= 0:
        errors["amount"] = "Enter an amount greater than 0"
        amount = None
    elif balance_cap is not None and amount > balance_cap:
        errors["amount"] = f"Only {balance_cap} remaining"
        amount = None
    elif amount is not None:
        amount = amount.quantize(Decimal("0.01"))
    mode = payload.get("payment_mode")
    if mode not in PAYMENT_MODES:
        errors["payment_mode"] = "Choose how it was paid"
    return amount, mode, errors


@bp.post("/api/fooding/me/expenses")
def add_my_expense():
    """A daily-wage worker spending some of their own fooding balance on something other than the
    automatic daily food deduction (kohal, 2026-10-18: "the daily wages employee can also use the money for
    travelling or for any reason... the amount, how was it paid and for what was it used") - capped at
    what's actually left, same as the admin can't approve a stock issue past what's in stock."""
    worker = own_worker()
    if worker is None or not worker.fooding_eligible:
        abort(403, "Fooding is only for daily-wage or fooding-eligible employees.")
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    account = account_for(worker, create=True)
    amount, mode, errors = _amount_and_mode(payload, balance_cap=account.remaining)
    purpose = str(payload.get("purpose") or "").strip()[:200]
    if not purpose:
        errors.setdefault("purpose", "Say what it was for")
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    account.deducted_total += amount
    db.session.add(FoodingEntry(account=account, kind="expense", amount=amount, payment_mode=mode,
                                 purpose=purpose, entry_date=today_local(), created_by_code=g.user.code))
    db.session.commit()
    return jsonify(fooding=account.to_dict(), entries=[e.to_dict() for e in account.entries]), 201


# ---------- admin/accountant management ----------

@bp.get("/api/fooding")
def list_fooding():
    _manage_only()
    workers = _fooding_eligible_query().order_by(Worker.name).all()
    accounts = {w.id: account_for(w) for w in workers}
    rows = [accounts[w.id].to_dict() if accounts[w.id] else _empty_dict(w) for w in workers]
    db.session.commit()
    return jsonify(workers=rows, daily_amount=float(FoodingAccount.DAILY_AMOUNT),
                   payment_modes=list(PAYMENT_MODES), currency=settings_for_client()["currency"])


@bp.get("/api/fooding/<int:worker_id>")
def register(worker_id):
    """One person's fooding register (kohal, 2026-10-27: "when clicking on one daily wages person, it should
    show credited, spent with date, who credited just like a register") - every top-up and every expense,
    newest first, each with its date, how it was paid and who entered it, plus how much the automatic daily
    deduction has taken so far (the account's deductions less the expenses someone logged)."""
    _manage_only()
    worker = _fooding_eligible_or_404(worker_id)
    account = account_for(worker)
    db.session.commit()
    entries = list(account.entries) if account else []
    spent = sum((e.amount for e in entries if e.kind == "expense"), Decimal("0"))
    auto = (account.deducted_total - spent) if account else Decimal("0")
    return jsonify(fooding=account.to_dict() if account else _empty_dict(worker),
                   entries=[e.to_dict() for e in entries], auto_deducted=float(max(auto, Decimal("0"))),
                   payment_modes=list(PAYMENT_MODES), currency=settings_for_client()["currency"])


@bp.post("/api/fooding/<int:worker_id>/allot")
def allot(worker_id):
    """Add to what's already allotted (kohal's own answer, 2026-10-18: a top-up adds to the remaining
    balance, it doesn't replace it) - creates the account on the very first allotment. Records how it was
    paid (kohal: "add mode of payment option as well") as its own FoodingEntry, not just a total."""
    _manage_only()
    worker = _fooding_eligible_or_404(worker_id)
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    amount, mode, errors = _amount_and_mode(payload)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    account = account_for(worker, create=True)
    account.allotted_total += amount
    db.session.add(FoodingEntry(account=account, kind="allot", amount=amount, payment_mode=mode,
                                 entry_date=today_local(), created_by_code=g.user.code))
    db.session.commit()
    return jsonify(fooding=account.to_dict())


def _set_paused(worker_id, paused):
    _manage_only()
    worker = _fooding_eligible_or_404(worker_id)
    account = account_for(worker, create=True)
    account.is_paused = paused
    db.session.commit()
    return jsonify(fooding=account.to_dict())


@bp.post("/api/fooding/<int:worker_id>/pause")
def pause(worker_id):
    return _set_paused(worker_id, True)


@bp.post("/api/fooding/<int:worker_id>/resume")
def resume(worker_id):
    return _set_paused(worker_id, False)

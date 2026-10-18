"""Fooding: a food allowance for daily-wage employees (kohal, 2026-10-18: "the admin or accountant will
alot some money to the daily wages employee. 200 rs per day should be deducted daily for food
automatically unless admin or accountant pauses that feature"). Not a module - nothing here is gated by
app/modules.py's check_module, since who may use it isn't a role-level thing (see auth.can_manage_fooding)
or depends on a personal HR detail (Worker.employment_type == "daily_wages") that cuts across roles, not a
service every role either has or doesn't.

Two audiences share one page, /fooding - same shape as /attendance's own team_only split (app/attendance.py):
- The admin or accountant allots money and pauses/resumes, for every daily-wage worker (kohal, 2026-10-18:
  "dude, fooding should open its own page!" - this used to only be a block on the Me hub, not a page).
- A daily-wage worker sees their own balance - allotted, remaining, and the ₹200/day note, or "Paused" -
  reached from a tile on their own Me hub (kohal: "when they login they should see attendance, wages and
  fooding") - alongside /wages (see app/wages.py), which exists but has nothing populated in it yet.

See FoodingAccount in app/models.py for how the running balance is kept current without a scheduled job."""

from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, g, jsonify, render_template, request

from .auth import can_manage_fooding
from .extensions import db
from .models import FoodingAccount, Worker, settings_for_client
from .validation import api_errors

bp = Blueprint("fooding", __name__)
api_errors(bp)


def _manage_only():
    if not can_manage_fooding(g.user):
        abort(403, "Only the admin or accountant can manage fooding.")


def own_worker():
    """The Worker row standing in for the signed-in person, if any - see auth.sync_worker_for_user. None
    for the admin, and for anyone who's never actually signed in to get one made."""
    return Worker.query.filter_by(user_code=g.user.code).first()


def _daily_wage_or_404(worker_id):
    worker = db.session.get(Worker, worker_id)
    if worker is None or worker.employment_type != "daily_wages":
        abort(404)
    return worker


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
    if worker is None or worker.employment_type != "daily_wages":
        abort(403, "Fooding is only for daily-wage employees.")
    return render_template("fooding.html", page_title="Fooding", mode="own")


@bp.get("/api/fooding/me")
def my_fooding():
    worker = own_worker()
    if worker is None or worker.employment_type != "daily_wages":
        abort(403, "Fooding is only for daily-wage employees.")
    account = account_for(worker)
    db.session.commit()
    return jsonify(fooding=account.to_dict() if account else _empty_dict(worker),
                   currency=settings_for_client()["currency"])


# ---------- admin/accountant management ----------

@bp.get("/api/fooding")
def list_fooding():
    _manage_only()
    workers = Worker.query.filter_by(employment_type="daily_wages").order_by(Worker.name).all()
    accounts = {w.id: account_for(w) for w in workers}
    rows = [accounts[w.id].to_dict() if accounts[w.id] else _empty_dict(w) for w in workers]
    db.session.commit()
    return jsonify(workers=rows, daily_amount=float(FoodingAccount.DAILY_AMOUNT), currency=settings_for_client()["currency"])


@bp.post("/api/fooding/<int:worker_id>/allot")
def allot(worker_id):
    """Add to what's already allotted (kohal's own answer, 2026-10-18: a top-up adds to the remaining
    balance, it doesn't replace it) - creates the account on the very first allotment."""
    _manage_only()
    worker = _daily_wage_or_404(worker_id)
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    try:
        amount = Decimal(str(payload.get("amount")))
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    if amount is None or not amount.is_finite() or amount <= 0:
        return jsonify(error="Check the highlighted fields", fields={"amount": "Enter an amount greater than 0"}), 422
    account = account_for(worker, create=True)
    account.allotted_total += amount.quantize(Decimal("0.01"))
    db.session.commit()
    return jsonify(fooding=account.to_dict())


def _set_paused(worker_id, paused):
    _manage_only()
    worker = _daily_wage_or_404(worker_id)
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

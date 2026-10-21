"""Cash purchases: money an admin or accountant hands an employee to go buy something with - fuel, a small
stock top-up, whatever comes up (kohal, 2026-10-21: "many a times, admin gives money to employees to
purchase a stock or fuel etc, we need to track that"). Not a module (app/modules.py) - same reasoning as
fooding (see app/fooding.py's own docstring): who may give or approve money isn't a role-level thing
(auth.can_manage_cash_purchases), and anyone with a Worker record can be on the receiving end, cutting
across every role rather than belonging to one.

Three steps, each its own API surface, no page of its own - everything here feeds a block on the Me hub
(kohal: "need this in me tab as cash purchase block of employees"), not a standalone route like /fooding:
  1. The admin/accountant gives cash (give() below) - applied immediately, same as fooding's own allot(),
     since the admin handing over the money *is* the fact, nothing to wait on.
  2. The employee logs what they actually bought with it (add_purchase()) - date, what, how much, how many,
     who from, a note, and (after the fact, its own upload endpoint) a bill - sitting pending until step 3.
  3. The admin/accountant approves or rejects it (approve()/reject()) - only once approved does the
     purchase's own amount count against the balance (CashAccount.spent_total), same request/approve shape
     as a material request (app/inventory.py), self-approval (and self-rejection) banned the same way.

See CashAccount/CashTopup/CashPurchase in app/models.py for the full data-model story."""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, g, jsonify, render_template, request

from .auth import can_manage_cash_purchases
from .extensions import db
from .models import CashAccount, CashPurchase, CashTopup, Worker, settings_for_client, utcnow
from .timeutil import today_local
from .uploads import DOCUMENT_TYPES, UploadError, delete_upload, save_upload
from .validation import Fields, api_errors

bp = Blueprint("cash_purchases", __name__)
api_errors(bp)

# Same fixed pair fooding uses (kohal, 2026-10-18, reused here 2026-10-21) - handing over cash or a UPI
# transfer in person, not the general PAYMENT_MODES list (Cheque/Bank transfer/Other don't apply).
PAYMENT_MODES = ("Cash", "Online/UPI")


def _manage_only():
    if not can_manage_cash_purchases(g.user):
        abort(403, "Only the admin or accountant can manage cash purchases.")


def own_worker():
    """The Worker row standing in for the signed-in person, if any - see auth.sync_worker_for_user. None
    for the admin, and for anyone who's never actually signed in to get one made."""
    return Worker.query.filter_by(user_code=g.user.code).first()


def account_for(worker, *, create=False):
    """This worker's cash account, or None if nothing's ever been given to them and `create` wasn't asked
    for. No settling needed here (unlike fooding's own account_for) - nothing accrues on its own, so the
    balance is already correct as of right now, every time."""
    account = worker.cash_account
    if account is None and create:
        account = CashAccount(worker=worker, given_total=Decimal("0"), spent_total=Decimal("0"))
        db.session.add(account)
    return account


def _payload():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    return payload


def _amount_and_mode(payload):
    """amount (a positive Decimal) and payment_mode (one of PAYMENT_MODES) from the request - for giving
    cash specifically (fooding's own _amount_and_mode, adapted - no balance_cap here, since there's no
    upper bound on how much an admin can hand someone)."""
    errors = {}
    try:
        amount = Decimal(str(payload.get("amount")))
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    if amount is None or not amount.is_finite() or amount <= 0:
        errors["amount"] = "Enter an amount greater than 0"
        amount = None
    elif amount is not None:
        amount = amount.quantize(Decimal("0.01"))
    mode = payload.get("payment_mode")
    if mode not in PAYMENT_MODES:
        errors["payment_mode"] = "Choose how it was paid"
    return amount, mode, errors


def _purchase_or_404(purchase_id):
    purchase = db.session.get(CashPurchase, purchase_id)
    if purchase is None:
        abort(404)
    return purchase


def _pending_or_409(purchase):
    if purchase.status != "pending":
        abort(409, "This entry isn't waiting for approval.")


# ---------- the employee's own balance and purchase log ----------

@bp.get("/api/cash-purchases/me")
def my_cash_purchases():
    worker = own_worker()
    if worker is None:
        abort(404)
    account = worker.cash_account
    return jsonify(
        account=account.to_dict() if account else None,
        entries=[p.to_dict() for p in account.purchases] if account else [],
        currency=settings_for_client()["currency"],
    )


def _purchase_fields(payload):
    f = Fields(payload)
    f.date("entry_date")
    f.text("material_name", 120, required=True, label="what was bought")
    f.text("unit", 20)
    f.text("supplier", 120)
    f.text("note", 500)
    f.money("quantity", nullable=True)
    f.money("amount", nullable=False)
    errors = f.errors

    if f.data.get("quantity") is not None and f.data["quantity"] <= 0:
        errors["quantity"] = "Enter a quantity greater than 0"
    amount = f.data.get("amount")
    if "amount" not in errors and (amount is None or amount <= 0):
        errors["amount"] = "Enter a cost greater than 0"

    return f, errors


@bp.post("/api/cash-purchases/me")
def add_purchase():
    """The employee's own "here's what I bought" entry (kohal, 2026-10-21: "purchase recorded by
    employee... date, material name, quantity, cost, supplier, notes, upload bill optional") - needs an
    account already (cash has to have been given before there's anything to log a purchase against), waits
    on the admin/accountant to approve before it touches the balance."""
    worker = own_worker()
    if worker is None:
        abort(404)
    account = worker.cash_account
    if account is None:
        abort(422, "No cash has been given to you yet.")
    payload = _payload()
    f, errors = _purchase_fields(payload)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    purchase = CashPurchase(
        account=account, entry_date=f.data.get("entry_date") or today_local(),
        material_name=f.data["material_name"], quantity=f.data.get("quantity"),
        unit=f.data.get("unit", ""), amount=f.data["amount"], supplier=f.data.get("supplier", ""),
        note=f.data.get("note", ""), created_by_code=g.user.code, status="pending",
    )
    db.session.add(purchase)
    db.session.commit()
    return jsonify(entry=purchase.to_dict()), 201


# ---------- the bill, attached after the fact, same as a stock-in's own ----------

@bp.post("/api/cash-purchases/<int:purchase_id>/bill")
def upload_bill(purchase_id):
    purchase = _purchase_or_404(purchase_id)
    if purchase.created_by_code != g.user.code and not can_manage_cash_purchases(g.user):
        abort(403, "Only who logged this, or the admin/accountant, can attach a bill to it.")
    files = request.files.getlist("bill")
    if not files:
        abort(422, "Choose a file")
    try:
        filename = save_upload(files[0], "cash_purchases", allowed=DOCUMENT_TYPES)
    except UploadError as err:
        abort(422, err.message)
    if purchase.bill_filename:
        delete_upload("cash_purchases", purchase.bill_filename)
    purchase.bill_filename = filename
    db.session.commit()
    return jsonify(entry=purchase.to_dict()), 201


@bp.delete("/api/cash-purchases/<int:purchase_id>/bill")
def delete_bill(purchase_id):
    purchase = _purchase_or_404(purchase_id)
    if purchase.created_by_code != g.user.code and not can_manage_cash_purchases(g.user):
        abort(403, "Only who logged this, or the admin/accountant, can remove its bill.")
    if purchase.bill_filename:
        delete_upload("cash_purchases", purchase.bill_filename)
        purchase.bill_filename = None
        db.session.commit()
    return jsonify(entry=purchase.to_dict())


# ---------- admin/accountant: give cash, approve or reject what came of it ----------

@bp.get("/purchase-approvals")
def page():
    """Its own page off a Me-hub tile (kohal, 2026-10-21: "this pending approval should have its own block
    next to fooding. named as purchase approval - this is only visisble to admin. inside this there will be
    approvals and alocate cash (same as fooding types)") - same idea as /fooding's own management mode, but
    admin/accountant only, nothing for an ordinary employee to see here (their own balance and log stay on
    the Me hub itself - see app/static/js/me.js)."""
    _manage_only()
    return render_template("purchase_approvals.html", page_title="Purchase approval")


@bp.get("/api/cash-purchases/accounts")
def accounts():
    """Every employee cash has actually been given to, and how much they have left right now (kohal,
    2026-10-21: "the subtab should be allocated cash and balance and their it should show employees to whom
    cash is allocated and how much they have balance rn") - the list behind Purchase approval's own
    Allocated cash & balance subtab, plus what its own "+ Allocate cash" sheet needs (every worker to pick
    from, and the payment-mode choices) so that action stays a single round trip too."""
    _manage_only()
    rows = CashAccount.query.join(Worker).order_by(Worker.name).all()
    return jsonify(
        accounts=[a.to_dict() for a in rows],
        workers=[{"id": w.id, "name": w.name} for w in Worker.query.order_by(Worker.name).all()],
        payment_modes=list(PAYMENT_MODES),
        currency=settings_for_client()["currency"],
    )


@bp.get("/api/cash-purchases/<int:worker_id>")
def worker_history(worker_id):
    """One employee's own cash account and every purchase they've ever logged against it - pending,
    approved or rejected (kohal, 2026-10-21: "clicking on one employee should show the history of cash
    expense and whether approved or rejected") - same shape as my_cash_purchases, just for whichever
    employee the admin/accountant taps into from the balances list, not only their own."""
    _manage_only()
    worker = db.session.get(Worker, worker_id)
    if worker is None:
        abort(404)
    account = worker.cash_account
    return jsonify(
        worker={"id": worker.id, "name": worker.name},
        account=account.to_dict() if account else None,
        entries=[p.to_dict() for p in account.purchases] if account else [],
        currency=settings_for_client()["currency"],
    )


@bp.post("/api/cash-purchases/<int:worker_id>/give")
def give(worker_id):
    """Add to what's already been given (same answer kohal gave for fooding's own allot - a top-up adds to
    the balance, it doesn't replace it) - creates the account on the very first top-up. Anyone with a
    Worker record can receive cash this way; there's no opt-in checkbox the way fooding has, since this
    isn't a standing wallet everyone either is or isn't on - it's just "did the admin ever hand this
    specific person money"."""
    _manage_only()
    worker = db.session.get(Worker, worker_id)
    if worker is None:
        abort(404)
    payload = _payload()
    amount, mode, errors = _amount_and_mode(payload)
    note = str(payload.get("note") or "").strip()[:200]
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    account = account_for(worker, create=True)
    account.given_total += amount
    db.session.add(CashTopup(account=account, amount=amount, payment_mode=mode, note=note,
                              entry_date=today_local(), created_by_code=g.user.code))
    db.session.commit()
    return jsonify(account=account.to_dict())


@bp.get("/api/cash-purchases/pending")
def pending():
    """Everyone's pending purchase entries in one place, plus what the "+ Give cash" sheet needs (every
    worker to pick from, and the payment-mode choices) - one round trip for the whole admin-facing block."""
    _manage_only()
    rows = CashPurchase.query.filter_by(status="pending").order_by(CashPurchase.created_at).all()
    return jsonify(
        pending=[p.to_dict() for p in rows],
        workers=[{"id": w.id, "name": w.name} for w in Worker.query.order_by(Worker.name).all()],
        payment_modes=list(PAYMENT_MODES),
        currency=settings_for_client()["currency"],
    )


@bp.post("/api/cash-purchases/<int:purchase_id>/approve")
def approve(purchase_id):
    _manage_only()
    purchase = _purchase_or_404(purchase_id)
    _pending_or_409(purchase)
    if purchase.created_by_code == g.user.code:
        abort(403, "Someone else needs to approve this - not whoever logged it.")
    purchase.status = "approved"
    purchase.approved_by_code = g.user.code
    purchase.approved_at = utcnow()
    purchase.account.spent_total += purchase.amount
    db.session.commit()
    return jsonify(entry=purchase.to_dict())


@bp.post("/api/cash-purchases/<int:purchase_id>/reject")
def reject(purchase_id):
    _manage_only()
    purchase = _purchase_or_404(purchase_id)
    _pending_or_409(purchase)
    if purchase.created_by_code == g.user.code:
        abort(403, "Someone else needs to decide this - not whoever logged it.")
    purchase.status = "rejected"
    purchase.approved_by_code = g.user.code
    purchase.approved_at = utcnow()
    db.session.commit()
    return jsonify(entry=purchase.to_dict())

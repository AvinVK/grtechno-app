"""Cash purchases: money an admin or accountant hands an employee to go buy something with - fuel, a small
stock top-up, whatever comes up (kohal, 2026-10-21: "many a times, admin gives money to employees to
purchase a stock or fuel etc, we need to track that"). Not a module (app/modules.py) - same reasoning as
fooding (see app/fooding.py's own docstring): who may give or approve money isn't a role-level thing
(auth.can_manage_cash_purchases), and anyone with a Worker record can be on the receiving end, cutting
across every role rather than belonging to one.

Four steps, each its own API surface, no page of its own - everything here feeds a block on the Me hub
(kohal: "need this in me tab as cash purchase block of employees"), not a standalone route like /fooding:
  0. The employee asks for cash up front (kohal, 2026-10-21: "employee requests for cash, admin sees the
     request -> allocates money") - request_cash() below, optional: the admin can always just give() cash
     unprompted too, same as before this step existed.
  1. The admin/accountant gives cash (give() below) - applied immediately, same as fooding's own allot(),
     since the admin handing over the money *is* the fact, nothing to wait on. Closes out a pending request
     as fulfilled when one prompted it.
  2. The employee logs what they actually bought with it (add_purchase()) - date, what, how much, how many,
     who from, a note, and (after the fact, its own upload endpoint) a bill - sitting pending until step 3.
  3. The admin/accountant approves or rejects it (approve()/reject()) - only once approved does the
     purchase's own amount count against the balance (CashAccount.spent_total), same request/approve shape
     as a material request (app/inventory.py), self-approval (and self-rejection) banned the same way.

See CashAccount/CashRequest/CashTopup/CashPurchase in app/models.py for the full data-model story."""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, g, jsonify, render_template, request

from .constants import EXPENSE_HEADS, PAYMENT_ACCOUNTS
from .auth import PROJECT_MANAGER_ROLE_KEYS, can_manage_cash_purchases
from .extensions import db
from .fooding import FOODING_SOURCE, raise_auto_topup
from .models import (
    AdminPurchase, CashAccount, CashPurchase, CashRequest, CashTopup, FoodingEntry, Material, MaterialUnit, Supplier, Worker, settings_for_client, utcnow,
)
from .timeutil import today_local
from .uploads import DOCUMENT_TYPES, UploadError, delete_upload, save_upload
from .validation import Fields, api_errors

bp = Blueprint("cash_purchases", __name__)
api_errors(bp)

# Same fixed pair fooding uses (kohal, 2026-10-18, reused here 2026-10-21) - handing over cash or a UPI
# transfer in person, not the general PAYMENT_MODES list (Cheque/Bank transfer/Other don't apply).
PAYMENT_MODES = tuple(PAYMENT_ACCOUNTS)       # the same accounts as everywhere else (kohal, 2026-10-31)
CATEGORIES = ("material", "other")             # what a purchase was for (kohal, 2026-11-04) - material gets stocked in on approval


def _manage_only():
    if not can_manage_cash_purchases(g.user):
        abort(403, "Only the admin or accountant can manage cash purchases.")


def _admin_decides():
    """Approving or rejecting here, and handing cash over, is the admin's alone (kohal, 2026-11-02: "for all the cash
    approvals in purchase approval and in fooding, only admin can approve it since only admin can open the phonepe app
    and pay through the bank accounts"). The accountant still sees these screens and can log things."""
    if not g.user.is_admin:
        abort(403, "Only the admin can approve cash or hand it over - it is paid out through the bank accounts.")


def own_worker():
    """The Worker row standing in for the signed-in person, if any - see auth.sync_worker_for_user. None
    for the admin, and for anyone who's never actually signed in to get one made."""
    return Worker.query.filter_by(user_code=g.user.code).first()


def _in_cash_flow(user) -> bool:
    """Who gets the employee-side cash flow - their balance, Request cash and Log purchase (kohal, 2026-11-05: "everything of
    the cash flow stays but only for project manager, accountant and admin"). Everyone else never sees it. The admin has no
    employee record of their own, so for them it is simply never shown - their own buying goes through Admin purchase."""
    return user.is_admin or user.role_key in PROJECT_MANAGER_ROLE_KEYS or user.role_key == "accounts"


def _cash_eligible(worker) -> bool:
    """Whether the admin may give this person cash (kohal, 2026-11-05: "admin should be able to allocate cash to only" project
    managers and accountants) - someone with a sign-in in one of those roles - and daily-wage workers, who are given cash for
    small things like petrol servicing, taken from their fooding balance (see give()). Neither has to log purchases the way a
    project manager does; a daily-wage worker just receives it. Anyone else is out."""
    user = worker.linked_user
    if user and (user.role_key in PROJECT_MANAGER_ROLE_KEYS or user.role_key == "accounts"):
        return True
    return worker.employment_type == "daily_wages" or worker.fooding_eligible


def _can_request_cash(worker) -> bool:
    """Daily-wage pay settles day by day already (kohal, 2026-10-21: "daily wages employee should not be
    able to request for cash") - the request-ahead step is for everyone else, who don't have that same
    daily cash-out to fall back on. Doesn't touch give() or the rest of the feature - the admin can still
    hand a daily-wage worker cash unprompted, and they can still log what they bought with it, same as
    before this restriction."""
    # (kohal, 2026-11-02: "for daily wages, remove this request cash" - their money comes through the fooding wallet,
    # which asks the admin for a top-up by itself when it runs low.)
    # And only project managers and accountants raise one (kohal, 2026-11-04: "remove cash request for all except
    # project manager and accountant") - everyone else is given cash by the admin unprompted, as before.
    return worker.employment_type != "daily_wages" and _in_cash_flow(g.user)


def account_for(worker, *, create=False):
    """This worker's cash account, or None if nothing's ever been given to them and `create` wasn't asked
    for. No settling needed here (unlike fooding's own account_for) - nothing accrues on its own, so the
    balance is already correct as of right now, every time."""
    account = worker.cash_account
    if account is None and create:
        account = CashAccount(worker=worker, given_total=Decimal("0"), spent_total=Decimal("0"))
        db.session.add(account)
    return account


def _fooding_left(worker):
    """What is left in this worker's fooding wallet today, or None if they have no wallet (not fooding-eligible).
    Settles the daily deduction first, so the figure is right as of now; the caller commits."""
    if not worker.fooding_eligible:
        return None
    account = worker.fooding_account
    if account is None:
        return Decimal("0")
    account.settle()
    raise_auto_topup(account)
    return account.remaining


def _worker_rows():
    rows = []
    for w in Worker.query.order_by(Worker.name).all():
        if not _cash_eligible(w):
            continue                       # only project managers and accountants can be given cash
        left = _fooding_left(w)
        row = {"id": w.id, "name": w.name, "fooding_remaining": None if left is None else float(left)}
        if g.user.is_admin:        # who gets paid, for opening a payment app already filled in - only the admin pays
            row["upi_id"], row["phone"] = w.upi_id or "", w.phone or ""
        rows.append(row)
    db.session.commit()
    return rows


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


def _request_amount_and_note(payload):
    """amount (a positive Decimal) and note from the request - for the employee's own ask (request_cash
    below), same validation as _amount_and_mode's own amount but with no payment_mode (nothing's actually
    been paid yet)."""
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
    note = str(payload.get("note") or "").strip()[:500]
    return amount, note, errors


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
    if worker is None or not _in_cash_flow(g.user):
        abort(404)
    account = worker.cash_account
    return jsonify(
        account=account.to_dict() if account else None,
        entries=[p.to_dict() for p in account.purchases] if account else [],
        requests=[r.to_dict() for r in worker.cash_requests],
        can_request=_can_request_cash(worker),
        materials=[{"name": m.name, "unit": m.unit} for m in Material.query.filter_by(is_active=True).order_by(Material.name)],
        suppliers=[name for (name,) in db.session.query(Supplier.name).order_by(Supplier.name)],
        units=[u.name for u in MaterialUnit.query.order_by(MaterialUnit.name)],
        currency=settings_for_client()["currency"],
    )


def _own_pending_request(worker):
    return CashRequest.query.filter_by(worker_id=worker.id, status="pending").first()


@bp.post("/api/cash-purchases/requests")
def request_cash():
    """The employee's own ask for cash (kohal, 2026-10-21: "add cash request for employees so that admin
    sees the request and then alocates... employee requests for cash, admin sees the request -> allocates
    money") - purely a prompt for the admin/accountant to see on Purchase approval's own Cash requests
    subtab; nothing is actually given until they act on it through give() below. One pending request at a
    time per worker, same reasoning as a pending purchase - a second ask on top of an unanswered one would
    just be noise."""
    worker = own_worker()
    if worker is None:
        abort(404)
    if not _can_request_cash(worker):
        abort(403, "Only project managers and accountants can request cash.")
    if _own_pending_request(worker) is not None:
        abort(409, "You already have a request waiting on the admin.")
    payload = _payload()
    amount, note, errors = _request_amount_and_note(payload)
    left = _fooding_left(worker)
    if left is not None and amount is not None and amount > left:
        shown = f"{left:,.2f}".rstrip("0").rstrip(".")
        errors["amount"] = (f"Only {settings_for_client()['currency']}{shown} left in your fooding balance"
                            if left > 0 else "You have nothing left in your fooding balance")
    if errors:
        db.session.commit()
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    req = CashRequest(worker=worker, amount=amount, note=note, status="pending")
    db.session.add(req)
    db.session.commit()
    return jsonify(request=req.to_dict()), 201


def _purchase_fields(payload, require_head=False):
    f = Fields(payload)
    f.date("entry_date")
    f.text("material_name", 120, required=True, label="what was bought")
    f.choice("category", CATEGORIES)
    f.text("unit", 20)
    f.text("supplier", 120)
    f.text("note", 500)
    f.money("quantity", nullable=True)
    f.money("amount", nullable=False)
    f.money("gst_percent", nullable=True)
    errors = f.errors

    if f.data.get("quantity") is not None and f.data["quantity"] <= 0:
        errors["quantity"] = "Enter a quantity greater than 0"
    amount = f.data.get("amount")
    if "amount" not in errors and (amount is None or amount <= 0):
        errors["amount"] = "Enter a cost greater than 0"
    gst_percent = f.data.get("gst_percent") if f.data.get("category") == "material" else None     # GST is for material only
    if gst_percent is not None and (gst_percent < 0 or gst_percent > 100):
        errors["gst_percent"] = "Enter a percentage from 0 to 100"
    elif "amount" not in errors and amount is not None and amount > 0:
        # The cost typed is before GST; what was spent - and comes off the balance - is cost plus GST.
        gst_percent = gst_percent or Decimal("0")
        gst_amount = (amount * gst_percent / Decimal("100")).quantize(Decimal("0.01"))
        f.data["gst_percent"], f.data["gst_amount"], f.data["amount"] = gst_percent, gst_amount, amount + gst_amount
    if "category" not in f.data:                  # mandatory (kohal, 2026-11-04) - missing or blank
        errors["category"] = "Choose a category"
    # Only the admin's own purchase says which kind of expense it was (kohal, 2026-11-09: "only in the admin purchase") - office,
    # travel, fooding, stationery... An employee's logged purchase has no such field.
    if require_head and f.data.get("category") == "other":
        if payload.get("expense_head") in EXPENSE_HEADS:
            f.data["expense_head"] = payload["expense_head"]
        else:
            errors["expense_head"] = "Choose the expense type"
    else:
        f.data["expense_head"] = ""
    # A material purchase becomes a stock-in once approved, and a stock-in needs a count and a unit.
    if f.data.get("category") == "material":
        if f.data.get("quantity") is None:
            errors.setdefault("quantity", "Enter how many you bought")
        if not f.data.get("unit"):
            errors["unit"] = "Enter the unit (bags, kg, pcs...)"

    return f, errors


@bp.post("/api/cash-purchases/me")
def add_purchase():
    """The employee's own "here's what I bought" entry (kohal, 2026-10-21: "purchase recorded by
    employee... date, material name, quantity, cost, supplier, notes, upload bill optional") - needs an
    account already (cash has to have been given before there's anything to log a purchase against), waits
    on the admin/accountant to approve before it touches the balance."""
    worker = own_worker()
    if worker is None or not _in_cash_flow(g.user):
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
        category=f.data["category"], gst_percent=f.data.get("gst_percent") or 0, gst_amount=f.data.get("gst_amount") or 0,
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
    return render_template("purchase_approvals.html", page_title="Purchase approval", is_admin=g.user.is_admin)


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
        workers=_worker_rows(),
        payment_modes=list(PAYMENT_MODES),
        currency=settings_for_client()["currency"],
        pending_purchase_count=CashPurchase.query.filter_by(status="pending").count(),
        pending_request_count=CashRequest.query.filter_by(status="pending").count(),
        can_decide=g.user.is_admin,
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
        # Cash the admin handed over (kohal, 2026-11-02: "add cash credit approvals as well with date"), newest first.
        topups=[t.to_dict() for t in account.topups] if account else [],
        currency=settings_for_client()["currency"],
    )


@bp.post("/api/cash-purchases/<int:worker_id>/give")
def give(worker_id):
    """Add to what's already been given (same answer kohal gave for fooding's own allot - a top-up adds to
    the balance, it doesn't replace it) - creates the account on the very first top-up. Anyone with a
    Worker record can receive cash this way; there's no opt-in checkbox the way fooding has, since this
    isn't a standing wallet everyone either is or isn't on - it's just "did the admin ever hand this
    specific person money".

    An optional request_id (kohal, 2026-10-21: "clicking on [a cash request] should open allocate form") -
    the same form, just pre-filled from that request and closing it out as fulfilled once the cash is
    actually given, rather than leaving it to sit there answered but still "pending"."""
    _manage_only()
    _admin_decides()
    worker = db.session.get(Worker, worker_id)
    if worker is None:
        abort(404)
    if not _cash_eligible(worker):
        msg = "Cash can only be given to project managers and accountants"
        return jsonify(error=msg, fields={"worker_id": msg}), 422
    payload = _payload()
    amount, mode, errors = _amount_and_mode(payload)
    note = str(payload.get("note") or "").strip()[:200]
    # Cash for someone on the fooding wallet (a daily-wage worker) comes out of that wallet, not out of one of the
    # admin's accounts (kohal, 2026-11-02: "when the daily wages are requesting for cash, it should be deducted from
    # fooding allocated balance and not any admin accounts"), so there is no account to choose.
    left = _fooding_left(worker)
    if left is not None:
        errors.pop("payment_mode", None)
        mode = FOODING_SOURCE
        if amount is not None and amount > left:
            shown = f"{left:,.2f}".rstrip("0").rstrip(".")
            errors["amount"] = (f"Only {settings_for_client()['currency']}{shown} left in {worker.name}'s fooding balance"
                                if left > 0 else f"{worker.name} has nothing left in their fooding balance")
    cash_request = None
    request_id = payload.get("request_id")
    if request_id not in (None, ""):
        cash_request = db.session.get(CashRequest, request_id)
        if cash_request is None:
            errors.setdefault("request_id", "That request no longer exists")
        elif cash_request.worker_id != worker_id:
            errors.setdefault("request_id", "That request belongs to a different employee")
        elif cash_request.status != "pending":
            errors.setdefault("request_id", "That request has already been dealt with")
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    account = account_for(worker, create=True)
    account.given_total += amount
    if left is not None:
        wallet = worker.fooding_account
        wallet.deducted_total += amount
        db.session.add(FoodingEntry(account=wallet, kind="expense", amount=amount, payment_mode=FOODING_SOURCE,
                                    purpose=f"Cash for purchases{': ' + note if note else ''}"[:200],
                                    entry_date=today_local(), created_by_code=g.user.code))
    db.session.add(CashTopup(account=account, amount=amount, payment_mode=mode, note=note,
                              entry_date=today_local(), created_by_code=g.user.code))
    if cash_request is not None:
        cash_request.status = "fulfilled"
        cash_request.resolved_at = utcnow()
        cash_request.resolved_by_code = g.user.code
    db.session.commit()
    return jsonify(account=account.to_dict())


@bp.get("/api/cash-purchases/requests")
def pending_requests():
    """Every employee's unanswered ask for cash (kohal, 2026-10-21: "a cash requests subtab which will show
    user has requested for 5k") - the list behind Purchase approval's own Cash requests subtab; tapping one
    opens the same Allocate form as "+ Allocate cash" (see accounts() above), pre-filled from the request
    and passing its id along so give() can close it out as fulfilled."""
    _manage_only()
    rows = CashRequest.query.filter_by(status="pending").order_by(CashRequest.created_at).all()
    return jsonify(
        requests=[r.to_dict() for r in rows],
        workers=_worker_rows(),
        payment_modes=list(PAYMENT_MODES),
        currency=settings_for_client()["currency"],
        pending_purchase_count=CashPurchase.query.filter_by(status="pending").count(),
        can_decide=g.user.is_admin,
    )


@bp.post("/api/cash-purchases/requests/<int:request_id>/reject")
def reject_request(request_id):
    """Turn down a request without giving anything - the request's own counterpart to give() closing one
    out as fulfilled, for when the admin/accountant doesn't want to allocate against it at all."""
    _manage_only()
    _admin_decides()
    req = db.session.get(CashRequest, request_id)
    if req is None:
        abort(404)
    if req.status != "pending":
        abort(409, "This request has already been dealt with.")
    req.status = "rejected"
    req.resolved_at = utcnow()
    req.resolved_by_code = g.user.code
    db.session.commit()
    return jsonify(request=req.to_dict())


@bp.get("/api/cash-purchases/pending")
def pending():
    """Everyone's pending purchase entries in one place, plus what the "+ Give cash" sheet needs (every
    worker to pick from, and the payment-mode choices) - one round trip for the whole admin-facing block."""
    _manage_only()
    rows = CashPurchase.query.filter_by(status="pending").order_by(CashPurchase.created_at).all()
    return jsonify(
        pending=[p.to_dict() for p in rows],
        workers=_worker_rows(),
        payment_modes=list(PAYMENT_MODES),
        currency=settings_for_client()["currency"],
        pending_request_count=CashRequest.query.filter_by(status="pending").count(),
        can_decide=g.user.is_admin,
    )


@bp.post("/api/cash-purchases/<int:purchase_id>/approve")
def approve(purchase_id):
    _manage_only()
    _admin_decides()
    purchase = _purchase_or_404(purchase_id)
    _pending_or_409(purchase)
    purchase.status = "approved"
    purchase.approved_by_code = g.user.code
    purchase.approved_at = utcnow()
    purchase.account.spent_total += purchase.amount
    if purchase.category == "material":
        problem = _stock_in_or_problem(purchase, f"Cash purchase by {purchase.account.worker.name}")
        if problem:
            return jsonify(error=problem), 422
    db.session.commit()
    return jsonify(entry=purchase.to_dict())


def _stock_in_or_problem(purchase, default_note):
    """_stock_in_purchase, or - when the material's own stock history is already broken (an earlier issue uses more than was in
    stock at the time) - nothing saved and the message naming that entry, as Inventory itself says it (kohal, 2026-11-08: this
    used to crash with a server error on the Purchase approval page)."""
    from .inventory import _NegativeStock, _negative_stock_message
    try:
        _stock_in_purchase(purchase, default_note)
    except _NegativeStock as exc:
        msg = _negative_stock_message(exc.movement.material, exc.movement)
        db.session.rollback()
        return f"Can't add this to Inventory yet: {msg}"
    return None


def _stock_in_purchase(purchase, default_note):
    """An approved material purchase goes straight into Inventory as an (already approved) cash stock-in
    (kohal, 2026-11-04) - the material is found by name, or added if it is new. No payment account is set on
    it: the money already left an account when the cash was given (CashTopup), so naming one here would count
    it twice on the Accounts page. Also used for an admin purchase, whose own row is what Accounts reads. The employee's supplier text becomes a Supplier (new ones are added) so it
    shows up on the supplier's own history."""
    from .inventory import _recompute_material
    from .models import MaterialMovement

    if purchase.movement_id is not None:
        return
    name = purchase.material_name.strip()
    material = Material.query.filter(db.func.lower(Material.name) == name.lower()).first()
    if material is None:
        material = Material(name=name[:120], unit=purchase.unit)
        db.session.add(material)
    elif not material.unit and purchase.unit:
        material.unit = purchase.unit
    if purchase.unit and not MaterialUnit.query.filter(db.func.lower(MaterialUnit.name) == purchase.unit.lower()).first():
        db.session.add(MaterialUnit(name=purchase.unit))
    supplier = None
    if purchase.supplier:
        supplier = Supplier.query.filter(db.func.lower(Supplier.name) == purchase.supplier.lower()).first()
        if supplier is None:
            supplier = Supplier(name=purchase.supplier[:160])
            db.session.add(supplier)
    qty = purchase.quantity
    cost = purchase.amount - purchase.gst_amount         # before GST - a stock-in values stock pre-GST
    movement = MaterialMovement(
        material=material, kind="in", quantity=qty, rate=(cost / qty).quantize(Decimal("0.01")),
        amount=cost, gst_percent=purchase.gst_percent, gst_amount=purchase.gst_amount, total_cost=purchase.amount,
        supplier=supplier, payment_mode="cash",
        note=(purchase.note or default_note)[:200], entry_date=purchase.entry_date,
        bill_filename=None, created_by_code=purchase.created_by_code, status="approved",
        approved_by_code=g.user.code, approved_at=utcnow(),
    )
    db.session.add(movement)
    db.session.flush()
    purchase.movement_id = movement.id
    _recompute_material(material)


@bp.post("/api/cash-purchases/<int:purchase_id>/reject")
def reject(purchase_id):
    _manage_only()
    _admin_decides()
    purchase = _purchase_or_404(purchase_id)
    _pending_or_409(purchase)
    purchase.status = "rejected"
    purchase.approved_by_code = g.user.code
    purchase.approved_at = utcnow()
    db.session.commit()
    return jsonify(entry=purchase.to_dict())


# ---------- Admin purchases: what the admin buys directly (kohal, 2026-11-04) ----------
#
# The admin pays from one of their own accounts, so there is no cash to allot and no approval step: it is saved
# straight away and, for a material, stocked into Inventory in the same step. Admin only - it is paid out through
# the bank accounts, same reasoning as every other payout here (_admin_decides).

def _admin_purchase_or_404(purchase_id):
    purchase = db.session.get(AdminPurchase, purchase_id)
    if purchase is None:
        abort(404)
    return purchase


@bp.get("/api/admin-purchases")
def list_admin_purchases():
    _manage_only()
    _admin_decides()
    rows = AdminPurchase.query.order_by(AdminPurchase.entry_date.desc(), AdminPurchase.id.desc()).all()
    return jsonify(
        entries=[p.to_dict() for p in rows],
        materials=[{"name": m.name, "unit": m.unit} for m in Material.query.filter_by(is_active=True).order_by(Material.name)],
        suppliers=[name for (name,) in db.session.query(Supplier.name).order_by(Supplier.name)],
        units=[u.name for u in MaterialUnit.query.order_by(MaterialUnit.name)],
        expense_heads=EXPENSE_HEADS,
        payment_accounts=list(PAYMENT_ACCOUNTS),
        currency=settings_for_client()["currency"],
    )


@bp.post("/api/admin-purchases")
def add_admin_purchase():
    _manage_only()
    _admin_decides()
    payload = _payload()
    f, errors = _purchase_fields(payload, require_head=True)
    account = payload.get("payment_account")
    if account not in PAYMENT_ACCOUNTS:
        errors["payment_account"] = "Choose the account it was paid from"
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    purchase = AdminPurchase(
        category=f.data["category"], expense_head=f.data.get("expense_head", ""), entry_date=f.data.get("entry_date") or today_local(),
        material_name=f.data["material_name"], quantity=f.data.get("quantity"), unit=f.data.get("unit", ""),
        gst_percent=f.data.get("gst_percent") or 0, gst_amount=f.data.get("gst_amount") or 0, amount=f.data["amount"],
        supplier=f.data.get("supplier", ""), note=f.data.get("note", ""), payment_account=account,
        created_by_code=g.user.code,
    )
    db.session.add(purchase)
    if purchase.category == "material":
        problem = _stock_in_or_problem(purchase, f"Admin purchase ({account})")
        if problem:
            return jsonify(error=problem), 422
    db.session.commit()
    return jsonify(entry=purchase.to_dict()), 201


@bp.post("/api/admin-purchases/<int:purchase_id>/bill")
def upload_admin_purchase_bill(purchase_id):
    _manage_only()
    _admin_decides()
    purchase = _admin_purchase_or_404(purchase_id)
    files = request.files.getlist("bill")
    if not files:
        abort(422, "Choose a file")
    try:
        filename = save_upload(files[0], "admin_purchases", allowed=DOCUMENT_TYPES)
    except UploadError as err:
        abort(422, err.message)
    if purchase.bill_filename:
        delete_upload("admin_purchases", purchase.bill_filename)
    purchase.bill_filename = filename
    db.session.commit()
    return jsonify(entry=purchase.to_dict()), 201

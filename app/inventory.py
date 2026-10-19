"""Inventory (admin only, for now - see reference_data.ADMIN_ONLY_MODULES): materials bought in bulk and
issued out to projects as they're used.

Stock and its cost live on the Material row (stock_qty, avg_rate), moved only through MaterialMovement
entries - never edited directly, so the two always add up:
  - stock-in (a purchase or receipt): quantity and rate are both given; the new quantity adds to stock_qty,
    and avg_rate becomes the weighted average of what was already in stock and what just came in.
  - issue (material used on a project): quantity only - it draws down stock_qty at the average rate
    already on the row, so the project's cost reflects what the stock actually cost, not a guess.
"""

import json
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, g, jsonify, render_template, request
from werkzeug.exceptions import abort

from .auth import can_approve_stock_in, visible_projects
from .extensions import db
from .modules import check_module
from .models import Material, MaterialMovement, MaterialUnit, Project, Supplier, Worker, settings_for_client, utcnow
from .timeutil import today_local
from .uploads import DOCUMENT_TYPES, UploadError, delete_upload, save_upload
from .validation import Fields, api_errors

bp = Blueprint("inventory", __name__)
api_errors(bp)

FREQUENCY_CHOICES = ("", "every_project", "special_project", "occasional")
USED_IN_MAX_ITEMS = 10
# A fixed set of suggestions for "how it was transported" - free text is still accepted (see
# _transport_fields), same "pick one or type your own" shape as Unit.
TRANSPORT_MODES = ("Own vehicle", "Company vehicle", "Courier", "Hand carried")


@bp.before_request
def _inventory_service():
    check_module("inventory")


def _payload():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    return payload


def _material_or_404(material_id: int) -> Material:
    material = db.session.get(Material, material_id)
    if material is None:
        abort(404)
    return material


def _movement_or_404(material: Material, movement_id: int) -> MaterialMovement:
    movement = next((mv for mv in material.movements if mv.id == movement_id), None)
    if movement is None:
        abort(404)
    return movement


def _used_in_list(payload, f):
    """Which fire-protection system(s) a material is used in - any number of the fixed categories, plus
    whatever was typed for "Other - specify". Not a Fields.choice (that's one value, not several), so this
    is handled by hand and stored as JSON - see Material.used_in."""
    if "used_in" not in payload:
        return
    raw = payload.get("used_in")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        f.errors["used_in"] = "Choose from the list"
        return
    cleaned, seen = [], set()
    for item in raw:
        if not isinstance(item, str):
            continue
        item = item.strip()[:60]
        if not item or item.lower() in seen:
            continue
        seen.add(item.lower())
        cleaned.append(item)
    f.data["used_in"] = json.dumps(cleaned[:USED_IN_MAX_ITEMS])


def _material_fields(payload, required=False):
    f = Fields(payload)
    f.text("name", 120, required=required, label="the material's name")
    f.text("unit", 20)
    f.text("notes", 400)
    f.choice("frequency", FREQUENCY_CHOICES)
    _used_in_list(payload, f)
    if f.data.get("name"):
        dupe = Material.query.filter(db.func.lower(Material.name) == f.data["name"].lower())
        clash = dupe.first()
        if clash is not None and request.view_args.get("material_id") != clash.id:
            f.errors["name"] = "A material with that name already exists"
            f.data.pop("name", None)
    unit = f.data.get("unit")
    if unit and not MaterialUnit.query.filter(db.func.lower(MaterialUnit.name) == unit.lower()).first():
        db.session.add(MaterialUnit(name=unit))        # grow the picker's list - see MaterialUnit
    return f


def _supply_fields(payload, *, require_quantity):
    """Supply detail for a purchase - quantity, cost, who it was bought from, the bill and GST. Required
    together for an explicit stock-in; on Add material, a brand-new material's first purchase is optional,
    but once either quantity or rate is given, both are needed (so it's never stocked with a quantity but
    no cost, or vice versa). GST amount and total cost are always computed here, never trusted from the
    client - see _apply_stock_in."""
    f = Fields(payload)
    f.money("quantity", nullable=True)
    f.money("rate", nullable=True)
    f.date("entry_date")
    f.text("note", 200)
    f.text("bill_no", 60)
    f.choice("payment_mode", ("credit", "cash"))
    f.money("gst_percent", nullable=True)
    has_qty = f.data.get("quantity") is not None
    has_rate = f.data.get("rate") is not None
    wants_stock = has_qty or has_rate or require_quantity
    if wants_stock:
        if not has_qty:
            f.errors.setdefault("quantity", "Enter a quantity greater than 0")
        elif f.data["quantity"] <= 0:
            f.errors["quantity"] = "Enter a quantity greater than 0"
        if not has_rate:
            f.errors.setdefault("rate", "Enter a cost per unit")
    if f.data.get("gst_percent") is not None and f.data["gst_percent"] > 100:
        f.errors["gst_percent"] = "Enter a percentage from 0 to 100"
    if not f.data.get("entry_date") and "entry_date" not in f.errors:
        f.data["entry_date"] = today_local()
    supplier_id = payload.get("supplier_id")
    if supplier_id not in (None, ""):
        supplier = db.session.get(Supplier, int(supplier_id)) if str(supplier_id).isdigit() else None
        if supplier is None:
            f.errors["supplier_id"] = "Pick a supplier"
        else:
            f.data["supplier_id"] = supplier.id
    return f, wants_stock


def _status_fields(approved):
    """status/approved_by/approved_at for a new movement - a stock-in is approved straight away if the
    person creating it is themselves someone who could approve it (auth.can_approve_stock_in), otherwise
    left pending for whoever can; an issue straight from Inventory (not a project's request) is always
    approved on the spot - whoever's creating it already has Inventory access (kohal, 2026-10-16/17)."""
    return dict(
        status="approved" if approved else "pending",
        approved_by_code=g.user.code if approved else None,
        approved_at=utcnow() if approved else None,
    )


def _apply_stock_in(material, data):
    """Create a stock-in movement. Stock itself (stock_qty/avg_rate) is never touched directly here - even
    when this request is approved on the spot, _recompute_material (called right after, by the caller) is
    the one source of truth for the blend, so an approved-later request goes through exactly the same math
    as one approved immediately."""
    qty, rate = data["quantity"], data["rate"]
    amount = qty * rate
    gst_percent = data.get("gst_percent") or Decimal("0")
    gst_amount = (amount * gst_percent / Decimal("100")).quantize(Decimal("0.01"))
    movement = MaterialMovement(
        material=material, kind="in", quantity=qty, rate=rate, amount=amount,
        note=data.get("note", ""), entry_date=data["entry_date"], created_by_code=g.user.code,
        supplier_id=data.get("supplier_id"), bill_no=data.get("bill_no", ""),
        payment_mode=data.get("payment_mode", ""), gst_percent=gst_percent, gst_amount=gst_amount,
        total_cost=amount + gst_amount,
        **_status_fields(can_approve_stock_in(g.user)),
    )
    db.session.add(movement)
    return movement


def _validate_given_by(payload, f, *, required=False):
    given_by_worker_id = payload.get("given_by_worker_id")
    if given_by_worker_id in (None, ""):
        if required:
            f.errors.setdefault("given_by_worker_id", "Pick who took the material")
        return
    worker = db.session.get(Worker, int(given_by_worker_id)) if str(given_by_worker_id).isdigit() else None
    if worker is None:
        f.errors["given_by_worker_id"] = "Pick who took the material"
    else:
        f.data["given_by_worker_id"] = worker.id


def _transport_fields(payload, f, *, required):
    """How the material got from the store to the project, and when (kohal, 2026-10-17) - required when
    approving a request (that's the point of the whole flow), optional on a direct issue from Inventory
    itself, which can note it but isn't forced to."""
    mode = str(payload.get("transport_mode") or "").strip()[:40]
    if mode:
        f.data["transport_mode"] = mode
    elif required:
        f.errors.setdefault("transport_mode", "Choose how it was transported")
    raw = payload.get("transported_at")
    if raw not in (None, ""):
        try:
            f.data["transported_at"] = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            f.errors["transported_at"] = "Enter a valid date and time"
    elif required:
        f.data["transported_at"] = utcnow()


class _NegativeStock(Exception):
    """Raised mid-replay (see _recompute_material) - editing or deleting one entry can make a later issue
    exceed what's actually left in stock at that point, even if the material's final stock_qty would still
    come out non-negative overall."""


def _recompute_material(material):
    """Rebuild stock_qty/avg_rate (and, since an issue draws down at whatever the average happened to be at
    the time, every issue's own rate/amount snapshot) from scratch by replaying every *approved* movement
    for this material in date order - a pending or rejected one (see MaterialMovement.status) never
    happened as far as stock is concerned, so it's skipped here, not just hidden in the UI. Needed after
    editing, deleting or approving any one entry - avg_rate is a running weighted average, so touching one
    entry can change every average calculated after it, not just that row."""
    movements = (MaterialMovement.query.filter_by(material_id=material.id, status="approved")
                 .order_by(MaterialMovement.entry_date, MaterialMovement.id).all())
    stock_qty = Decimal("0")
    avg_rate = Decimal("0")
    for mv in movements:
        if mv.kind == "in":
            new_qty = stock_qty + mv.quantity
            if new_qty > 0:
                avg_rate = ((stock_qty * avg_rate) + (mv.quantity * mv.rate)) / new_qty
                avg_rate = avg_rate.quantize(Decimal("0.01"))
            stock_qty = new_qty
        else:
            if mv.quantity > stock_qty:
                raise _NegativeStock
            mv.rate = avg_rate
            mv.amount = (mv.quantity * avg_rate).quantize(Decimal("0.01"))
            stock_qty -= mv.quantity
    material.stock_qty = stock_qty
    material.avg_rate = avg_rate


def _movement_fields(payload, *, needs_project):
    f = Fields(payload)
    f.money("quantity", nullable=False)
    f.date("entry_date")
    f.text("note", 200)
    if needs_project:
        f.integer("project_id", low=1, high=999999999)
        if f.data.get("project_id") is None:
            if "project_id" not in f.errors:
                f.errors["project_id"] = "Pick a project"
        elif visible_projects().filter(Project.id == f.data["project_id"], Project.status != "completed").first() is None:
            f.errors["project_id"] = "Pick a project"
            f.data.pop("project_id", None)
    if f.data.get("quantity") is not None and f.data["quantity"] <= 0:
        f.errors["quantity"] = "Enter a quantity greater than 0"
    if not f.data.get("entry_date") and "entry_date" not in f.errors:
        f.data["entry_date"] = today_local()
    return f


@bp.get("/inventory")
def page():
    return render_template("inventory.html")


def _current_projects():
    """"Current projects" for the issue form's picker - not yet completed. visible_projects() already
    scopes this to what the signed-in person may see at all."""
    return visible_projects().filter(Project.status != "completed").order_by(Project.id.desc()).all()


def _suppliers_for_client():
    return [{"id": s.id, "name": s.name} for s in Supplier.query.order_by(Supplier.name).all()]


def _units_for_client():
    return [u.name for u in MaterialUnit.query.order_by(MaterialUnit.name).all()]


def _material_names():
    """Every material's name, for the Add/Edit material name field's autopredict - so a near-duplicate
    ("Cement" vs "cement bags") gets caught by typing, not just by the "already exists" error on save."""
    return [name for (name,) in db.session.query(Material.name).order_by(Material.name).all()]


def _workers_for_client():
    """Who can be picked as "Given by" on an issue - anyone on the Employee management list, not just
    sales (unlike Enquired by on leads), since it's whoever physically hands the material over."""
    return [{"id": w.id, "name": w.name} for w in Worker.query.order_by(Worker.name).all()]


@bp.get("/api/inventory/materials")
def list_materials():
    materials = Material.query.order_by(Material.is_active.desc(), Material.name).all()
    return jsonify(
        materials=[m.to_dict() for m in materials],
        projects=[{"id": p.id, "code": p.code, "title": p.title} for p in _current_projects()],
        suppliers=_suppliers_for_client(),
        workers=_workers_for_client(),
        units=_units_for_client(),
        material_names=_material_names(),
        total_stock_value=float(sum((m.stock_value for m in materials), start=0)),
        currency=settings_for_client()["currency"],
        # For the Material requests tab's badge (kohal, 2026-10-17) - cheap enough to just count here
        # rather than make the list page wait on a second request only to show a number on a tab.
        pending_request_count=MaterialMovement.query.filter_by(kind="out", status="pending").count(),
    )


@bp.post("/api/inventory/materials")
def add_material():
    payload = _payload()
    f = _material_fields(payload, required=True)
    sf, wants_stock = _supply_fields(payload, require_quantity=False)
    f.errors.update(sf.errors)
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    material = Material(**f.data)
    db.session.add(material)
    movement = None
    if wants_stock:
        db.session.flush()         # stock_qty/avg_rate need their column defaults applied before recompute
        movement = _apply_stock_in(material, sf.data)
        db.session.flush()
        if movement.status == "approved":
            _recompute_material(material)
    db.session.commit()
    return jsonify(material=material.to_dict(), movement=movement.to_dict() if movement else None), 201


@bp.get("/api/inventory/materials/<int:material_id>")
def get_material(material_id):
    material = _material_or_404(material_id)
    return jsonify(
        material=material.to_dict(),
        movements=[mv.to_dict() for mv in material.movements],
        projects=[{"id": p.id, "code": p.code, "title": p.title} for p in _current_projects()],
        suppliers=_suppliers_for_client(),
        workers=_workers_for_client(),
        units=_units_for_client(),
        material_names=_material_names(),
        currency=settings_for_client()["currency"],
        can_approve_stock_in=can_approve_stock_in(g.user),
    )


@bp.post("/api/inventory/suppliers")
def add_supplier():
    """Add a supplier, same "add new on the fly" pattern as Role (see app/roles.py) - just a name, no
    slug/key needed since nothing else references a supplier by a stable string key."""
    name = str(_payload().get("name") or "").strip()[:160]
    if not name:
        return jsonify(error="Check the highlighted fields", fields={"name": "Enter a supplier name"}), 422
    if Supplier.query.filter(db.func.lower(Supplier.name) == name.lower()).first():
        return jsonify(error="Check the highlighted fields", fields={"name": "That supplier already exists"}), 422
    supplier = Supplier(name=name)
    db.session.add(supplier)
    db.session.commit()
    return jsonify(supplier={"id": supplier.id, "name": supplier.name}), 201


@bp.patch("/api/inventory/materials/<int:material_id>")
def update_material(material_id):
    material = _material_or_404(material_id)
    payload = _payload()
    f = _material_fields(payload)
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    for key, value in f.data.items():
        setattr(material, key, value)
    if "is_active" in payload:
        material.is_active = bool(payload["is_active"])
    db.session.commit()
    return jsonify(material=material.to_dict())


@bp.post("/api/inventory/materials/<int:material_id>/stock-in")
def stock_in(material_id):
    material = _material_or_404(material_id)
    f, _ = _supply_fields(_payload(), require_quantity=True)
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    movement = _apply_stock_in(material, f.data)
    db.session.flush()
    if movement.status == "approved":
        try:
            _recompute_material(material)
        except _NegativeStock:
            db.session.rollback()
            return jsonify(error="This material's existing history has an issue somewhere already - an approved issue dated before the stock it drew down arrived. Fix the dates on its past entries first."), 422
    db.session.commit()
    return jsonify(material=material.to_dict(), movement=movement.to_dict()), 201


@bp.post("/api/inventory/materials/<int:material_id>/movements/<int:movement_id>/bill")
def upload_bill(material_id, movement_id):
    """The purchase's receipt or invoice - attached after the fact (it isn't always to hand when the
    stock-in itself is logged), and only for a stock-in, since an issue has no bill of its own."""
    material = _material_or_404(material_id)
    movement = _movement_or_404(material, movement_id)
    if movement.kind != "in":
        abort(422, "Only a stock-in entry can have a bill.")
    files = request.files.getlist("bill")
    if not files:
        abort(422, "Choose a file")
    try:
        filename = save_upload(files[0], "materials", allowed=DOCUMENT_TYPES)
    except UploadError as err:
        abort(422, err.message)
    if movement.bill_filename:
        delete_upload("materials", movement.bill_filename)
    movement.bill_filename = filename
    db.session.commit()
    return jsonify(movement=movement.to_dict()), 201


@bp.delete("/api/inventory/materials/<int:material_id>/movements/<int:movement_id>/bill")
def delete_bill(material_id, movement_id):
    material = _material_or_404(material_id)
    movement = _movement_or_404(material, movement_id)
    if movement.bill_filename:
        delete_upload("materials", movement.bill_filename)
        movement.bill_filename = None
        db.session.commit()
    return jsonify(movement=movement.to_dict())


@bp.post("/api/inventory/materials/<int:material_id>/issue")
def issue(material_id):
    """Issue straight from Inventory - not a project's request (see app/projects.py's material-requests,
    and this module's own material_requests/approve_material_request below) - so it's approved on the spot:
    whoever's doing this already has Inventory access, and is the one handing the material over right now
    (kohal, 2026-10-17)."""
    material = _material_or_404(material_id)
    payload = _payload()
    f = _movement_fields(payload, needs_project=True)
    if f.data.get("quantity") is not None and f.data["quantity"] > material.stock_qty:
        f.errors["quantity"] = f"Only {material.stock_qty} {material.unit or 'in'} stock"
    _validate_given_by(payload, f)
    _transport_fields(payload, f, required=False)
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    qty, rate = f.data["quantity"], material.avg_rate
    movement = MaterialMovement(
        material=material, kind="out", quantity=qty, rate=rate, amount=qty * rate,
        project_id=f.data["project_id"], note=f.data.get("note", ""), entry_date=f.data["entry_date"],
        created_by_code=g.user.code, given_by_worker_id=f.data.get("given_by_worker_id"),
        transport_mode=f.data.get("transport_mode", ""), transported_at=f.data.get("transported_at"),
        **_status_fields(True),
    )
    db.session.add(movement)
    db.session.flush()
    try:
        _recompute_material(material)
    except _NegativeStock:
        db.session.rollback()
        return jsonify(error="That leaves stock short on some date between then and now - check the date, or the quantities around it."), 422
    db.session.commit()
    return jsonify(material=material.to_dict(), movement=movement.to_dict()), 201


@bp.patch("/api/inventory/materials/<int:material_id>/movements/<int:movement_id>")
def update_movement(material_id, movement_id):
    """Fix a bulk-entry mistake on an already-saved stock-in or issue - quantity and (for a stock-in) cost
    are the usual culprits, but everything on the entry can be corrected. stock_qty/avg_rate (and every
    later issue's own rate snapshot) are rebuilt from scratch afterwards - see _recompute_material."""
    material = _material_or_404(material_id)
    movement = _movement_or_404(material, movement_id)
    payload = _payload()
    if movement.kind == "in":
        f, _ = _supply_fields(payload, require_quantity=True)
        if f.errors:
            return jsonify(error="Check the highlighted fields", fields=f.errors), 422
        amount = f.data["quantity"] * f.data["rate"]
        gst_percent = f.data.get("gst_percent") or Decimal("0")
        gst_amount = (amount * gst_percent / Decimal("100")).quantize(Decimal("0.01"))
        movement.quantity = f.data["quantity"]
        movement.rate = f.data["rate"]
        movement.amount = amount
        movement.entry_date = f.data["entry_date"]
        movement.note = f.data.get("note", "")
        movement.supplier_id = f.data.get("supplier_id")
        movement.bill_no = f.data.get("bill_no", "")
        movement.payment_mode = f.data.get("payment_mode", "")
        movement.gst_percent = gst_percent
        movement.gst_amount = gst_amount
        movement.total_cost = amount + gst_amount
    else:
        f = _movement_fields(payload, needs_project=True)
        _validate_given_by(payload, f)
        if f.errors:
            return jsonify(error="Check the highlighted fields", fields=f.errors), 422
        movement.quantity = f.data["quantity"]
        movement.project_id = f.data["project_id"]
        movement.entry_date = f.data["entry_date"]
        movement.note = f.data.get("note", "")
        movement.given_by_worker_id = f.data.get("given_by_worker_id")
    try:
        _recompute_material(material)
    except _NegativeStock:
        db.session.rollback()
        return jsonify(error="That leaves an issue later on exceeding what was in stock at the time - check the quantities around it."), 422
    db.session.commit()
    return jsonify(material=material.to_dict(), movement=movement.to_dict())


def approve_movement(movement, approver):
    """Approve a pending movement (see MaterialMovement.status) - the caller has already checked the
    approver is allowed to (can_approve_stock_in for a stock-in; every route in this module already needs
    Inventory access for an issue, see auth.can_approve_issue)."""
    movement.status = "approved"
    movement.approved_by_code = approver.code
    movement.approved_at = utcnow()
    _recompute_material(movement.material)


def reject_movement(movement, approver):
    """Reject a pending movement - permanent, same as a deleted one, but the row (and who turned it down)
    stays on record instead of disappearing."""
    movement.status = "rejected"
    movement.approved_by_code = approver.code
    movement.approved_at = utcnow()


def _pending_or_409(movement):
    if movement.status != "pending":
        abort(409, "This entry isn't waiting for approval.")


@bp.post("/api/inventory/materials/<int:material_id>/movements/<int:movement_id>/approve")
def approve_stock_in(material_id, movement_id):
    """Only a stock-in goes through here - an issue request is approved from the Material requests tab
    below (approve_material_request), which also records who took the material out and how."""
    material = _material_or_404(material_id)
    movement = _movement_or_404(material, movement_id)
    if movement.kind != "in":
        abort(422, "Approve an issue from its project instead.")
    _pending_or_409(movement)
    if not can_approve_stock_in(g.user):
        abort(403, "Only an accountant or office assistant can approve a stock-in.")
    try:
        approve_movement(movement, g.user)
    except _NegativeStock:
        db.session.rollback()
        return jsonify(error="Approving this would leave an issue dated after it exceeding what was in stock at the time."), 422
    db.session.commit()
    return jsonify(material=material.to_dict(), movement=movement.to_dict())


@bp.post("/api/inventory/materials/<int:material_id>/movements/<int:movement_id>/reject")
def reject_stock_in(material_id, movement_id):
    material = _material_or_404(material_id)
    movement = _movement_or_404(material, movement_id)
    if movement.kind != "in":
        abort(422, "Reject an issue request from the Material requests tab instead.")
    _pending_or_409(movement)
    if not can_approve_stock_in(g.user):
        abort(403, "Only an accountant or office assistant can reject a stock-in.")
    reject_movement(movement, g.user)
    db.session.commit()
    return jsonify(material=material.to_dict(), movement=movement.to_dict())


# ---------- Material requests (kohal, 2026-10-17, updated 2026-10-19) ----------
#
# Every pending issue ('out') request, gathered from every project, in one place - "anyone with Inventory
# access can approve", so this needs nothing beyond the blueprint's own check_module("inventory") gate
# above, except whoever asked for it in the first place (kohal, 2026-10-19: "creator user cannot be
# approval" - no self-approval, not even for an admin's own request); approving records who physically took
# the material out of the store, how, and when. Asking for more than what's in stock approves only what's
# there and splits the rest into a new pending request for the same project, which surfaces here again once
# there's enough stock.

def _material_request_dict(movement):
    d = movement.to_dict()
    d["material_name"] = movement.material.name
    d["material_code"] = movement.material.code
    d["unit"] = movement.material.unit
    d["stock_qty"] = float(movement.material.stock_qty)
    return d


@bp.get("/api/inventory/material-requests")
def material_requests():
    pending = (MaterialMovement.query.filter_by(kind="out", status="pending")
               .order_by(MaterialMovement.created_at).all())
    return jsonify(
        requests=[_material_request_dict(mv) for mv in pending],
        workers=_workers_for_client(),
        transport_modes=list(TRANSPORT_MODES),
    )


@bp.get("/api/inventory/material-requests/history")
def material_request_history():
    """Every request that's been dealt with, newest first - who asked, who approved or rejected it, and
    when (kohal, 2026-10-19: "we need to show material request history as well along with who approved
    it"), same section of the Material requests tab as the pending list above."""
    rows = (MaterialMovement.query.filter(MaterialMovement.kind == "out", MaterialMovement.status != "pending")
            .order_by(MaterialMovement.approved_at.desc(), MaterialMovement.created_at.desc())
            .limit(200).all())
    return jsonify(requests=[_material_request_dict(mv) for mv in rows])


@bp.post("/api/inventory/material-requests/<int:movement_id>/approve")
def approve_material_request(movement_id):
    movement = MaterialMovement.query.filter_by(id=movement_id, kind="out").first()
    if movement is None:
        abort(404)
    _pending_or_409(movement)
    if movement.created_by_code == g.user.code:
        abort(403, "Someone else needs to approve this - not whoever asked for it.")
    material = movement.material
    requested = movement.quantity
    payload = _payload()

    f = Fields(payload)
    f.money("quantity", nullable=False)
    qty = f.data.get("quantity")
    if qty is None:
        f.errors.setdefault("quantity", "Enter a quantity greater than 0")
    elif qty <= 0:
        f.errors["quantity"] = "Enter a quantity greater than 0"
    elif qty > requested:
        f.errors["quantity"] = f"Only {requested} {material.unit or ''} was requested".strip()
    elif qty > material.stock_qty:
        f.errors["quantity"] = f"Only {material.stock_qty} {material.unit or 'in'} stock"
    _validate_given_by(payload, f, required=True)
    _transport_fields(payload, f, required=True)
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422

    shortfall = requested - qty
    movement.quantity = qty
    movement.given_by_worker_id = f.data.get("given_by_worker_id")
    movement.transport_mode = f.data.get("transport_mode", "")
    movement.transported_at = f.data.get("transported_at")
    remainder = None
    if shortfall > 0:
        # The part that couldn't be covered stays as its own pending request against the same project, so
        # it's still there - and still flagged (see Material.pending_requested_qty) - once more stock comes
        # in, instead of silently losing track of what was short.
        remainder = MaterialMovement(
            material=material, kind="out", quantity=shortfall, rate=movement.rate, amount=shortfall * movement.rate,
            project_id=movement.project_id, note=movement.note, entry_date=movement.entry_date,
            created_by_code=movement.created_by_code, status="pending",
        )
        db.session.add(remainder)
    try:
        approve_movement(movement, g.user)
    except _NegativeStock:
        db.session.rollback()
        return jsonify(error="Approving this would leave stock negative - check what else has moved since it was requested."), 422
    db.session.commit()
    return jsonify(material=material.to_dict(), movement=_material_request_dict(movement),
                    remainder=_material_request_dict(remainder) if remainder else None)


@bp.post("/api/inventory/material-requests/<int:movement_id>/reject")
def reject_material_request(movement_id):
    movement = MaterialMovement.query.filter_by(id=movement_id, kind="out").first()
    if movement is None:
        abort(404)
    _pending_or_409(movement)
    reject_movement(movement, g.user)
    db.session.commit()
    return jsonify(movement=_material_request_dict(movement))


@bp.delete("/api/inventory/materials/<int:material_id>/movements/<int:movement_id>")
def delete_movement(material_id, movement_id):
    """Remove a bulk-entry mistake entirely, same recompute as update_movement above."""
    material = _material_or_404(material_id)
    movement = _movement_or_404(material, movement_id)
    bill_filename = movement.bill_filename
    db.session.delete(movement)
    try:
        _recompute_material(material)
    except _NegativeStock:
        db.session.rollback()
        return jsonify(error="Can't delete that - a later issue would exceed what was left in stock without it."), 422
    db.session.commit()
    if bill_filename:          # only delete the actual file once the row's gone for good, not before
        delete_upload("materials", bill_filename)
    return jsonify(material=material.to_dict())

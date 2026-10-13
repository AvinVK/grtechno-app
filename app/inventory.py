"""Inventory (admin only, for now - see reference_data.ADMIN_ONLY_MODULES): materials bought in bulk and
issued out to projects as they're used.

Stock and its cost live on the Material row (stock_qty, avg_rate), moved only through MaterialMovement
entries - never edited directly, so the two always add up:
  - stock-in (a purchase or receipt): quantity and rate are both given; the new quantity adds to stock_qty,
    and avg_rate becomes the weighted average of what was already in stock and what just came in.
  - issue (material used on a project): quantity only - it draws down stock_qty at the average rate
    already on the row, so the project's cost reflects what the stock actually cost, not a guess.
"""

from decimal import Decimal

from flask import Blueprint, g, jsonify, render_template, request
from werkzeug.exceptions import abort

from .auth import visible_projects
from .extensions import db
from .modules import check_module
from .models import Material, MaterialMovement, Project, Supplier, Worker, settings_for_client
from .timeutil import today_local
from .uploads import DOCUMENT_TYPES, UploadError, delete_upload, save_upload
from .validation import Fields, api_errors

bp = Blueprint("inventory", __name__)
api_errors(bp)


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


def _material_fields(payload, required=False):
    f = Fields(payload)
    f.text("name", 120, required=required, label="the material's name")
    f.text("unit", 20)
    f.text("notes", 400)
    if f.data.get("name"):
        dupe = Material.query.filter(db.func.lower(Material.name) == f.data["name"].lower())
        clash = dupe.first()
        if clash is not None and request.view_args.get("material_id") != clash.id:
            f.errors["name"] = "A material with that name already exists"
            f.data.pop("name", None)
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


def _apply_stock_in(material, data):
    qty, rate = data["quantity"], data["rate"]
    new_qty = material.stock_qty + qty
    blended = ((material.stock_qty * material.avg_rate) + (qty * rate)) / new_qty
    material.avg_rate = blended.quantize(Decimal("0.01"))
    material.stock_qty = new_qty
    amount = qty * rate
    gst_percent = data.get("gst_percent") or Decimal("0")
    gst_amount = (amount * gst_percent / Decimal("100")).quantize(Decimal("0.01"))
    movement = MaterialMovement(
        material=material, kind="in", quantity=qty, rate=rate, amount=amount,
        note=data.get("note", ""), entry_date=data["entry_date"], created_by_code=g.user.code,
        supplier_id=data.get("supplier_id"), bill_no=data.get("bill_no", ""),
        payment_mode=data.get("payment_mode", ""), gst_percent=gst_percent, gst_amount=gst_amount,
        total_cost=amount + gst_amount,
    )
    db.session.add(movement)
    return movement


def _validate_given_by(payload, f):
    given_by_worker_id = payload.get("given_by_worker_id")
    if given_by_worker_id not in (None, ""):
        worker = db.session.get(Worker, int(given_by_worker_id)) if str(given_by_worker_id).isdigit() else None
        if worker is None:
            f.errors["given_by_worker_id"] = "Pick who gave it out"
        else:
            f.data["given_by_worker_id"] = worker.id


class _NegativeStock(Exception):
    """Raised mid-replay (see _recompute_material) - editing or deleting one entry can make a later issue
    exceed what's actually left in stock at that point, even if the material's final stock_qty would still
    come out non-negative overall."""


def _recompute_material(material):
    """Rebuild stock_qty/avg_rate (and, since an issue draws down at whatever the average happened to be at
    the time, every issue's own rate/amount snapshot) from scratch by replaying every movement for this
    material in date order. Needed after editing or deleting any one entry - avg_rate is a running weighted
    average, so touching one entry can change every average calculated after it, not just that row."""
    movements = (MaterialMovement.query.filter_by(material_id=material.id)
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
        total_stock_value=float(sum((m.stock_value for m in materials), start=0)),
        currency=settings_for_client()["currency"],
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
    if wants_stock:
        db.session.flush()         # stock_qty/avg_rate need their column defaults applied before blending
    movement = _apply_stock_in(material, sf.data) if wants_stock else None
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
        currency=settings_for_client()["currency"],
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
    material = _material_or_404(material_id)
    payload = _payload()
    f = _movement_fields(payload, needs_project=True)
    if f.data.get("quantity") is not None and f.data["quantity"] > material.stock_qty:
        f.errors["quantity"] = f"Only {material.stock_qty} {material.unit or 'in'} stock"
    _validate_given_by(payload, f)
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    qty, rate = f.data["quantity"], material.avg_rate
    material.stock_qty -= qty
    movement = MaterialMovement(
        material=material, kind="out", quantity=qty, rate=rate, amount=qty * rate,
        project_id=f.data["project_id"], note=f.data.get("note", ""), entry_date=f.data["entry_date"],
        created_by_code=g.user.code, given_by_worker_id=f.data.get("given_by_worker_id"),
    )
    db.session.add(movement)
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

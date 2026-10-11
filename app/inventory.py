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
from .models import Material, MaterialMovement, Project, settings_for_client
from .timeutil import today_local
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
        elif visible_projects().filter(Project.id == f.data["project_id"]).first() is None:
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


@bp.get("/api/inventory/materials")
def list_materials():
    materials = Material.query.order_by(Material.is_active.desc(), Material.name).all()
    projects = visible_projects().order_by(Project.id.desc()).all()
    return jsonify(
        materials=[m.to_dict() for m in materials],
        projects=[{"id": p.id, "code": p.code, "title": p.title} for p in projects],
        total_stock_value=float(sum((m.stock_value for m in materials), start=0)),
        currency=settings_for_client()["currency"],
    )


@bp.post("/api/inventory/materials")
def add_material():
    f = _material_fields(_payload(), required=True)
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    material = Material(**f.data)
    db.session.add(material)
    db.session.commit()
    return jsonify(material=material.to_dict()), 201


@bp.get("/api/inventory/materials/<int:material_id>")
def get_material(material_id):
    material = _material_or_404(material_id)
    return jsonify(
        material=material.to_dict(),
        movements=[mv.to_dict() for mv in material.movements],
        projects=[{"id": p.id, "code": p.code, "title": p.title} for p in visible_projects().order_by(Project.id.desc()).all()],
        currency=settings_for_client()["currency"],
    )


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
    payload = _payload()
    f = _movement_fields(payload, needs_project=False)
    f.money("rate", nullable=False)
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    qty, rate = f.data["quantity"], f.data["rate"]
    new_qty = material.stock_qty + qty
    blended = ((material.stock_qty * material.avg_rate) + (qty * rate)) / new_qty
    material.avg_rate = blended.quantize(Decimal("0.01"))
    material.stock_qty = new_qty
    movement = MaterialMovement(
        material=material, kind="in", quantity=qty, rate=rate, amount=qty * rate,
        note=f.data.get("note", ""), entry_date=f.data["entry_date"], created_by_code=g.user.code,
    )
    db.session.add(movement)
    db.session.commit()
    return jsonify(material=material.to_dict(), movement=movement.to_dict()), 201


@bp.post("/api/inventory/materials/<int:material_id>/issue")
def issue(material_id):
    material = _material_or_404(material_id)
    payload = _payload()
    f = _movement_fields(payload, needs_project=True)
    if f.data.get("quantity") is not None and f.data["quantity"] > material.stock_qty:
        f.errors["quantity"] = f"Only {material.stock_qty} {material.unit or 'in'} stock"
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    qty, rate = f.data["quantity"], material.avg_rate
    material.stock_qty -= qty
    movement = MaterialMovement(
        material=material, kind="out", quantity=qty, rate=rate, amount=qty * rate,
        project_id=f.data["project_id"], note=f.data.get("note", ""), entry_date=f.data["entry_date"],
        created_by_code=g.user.code,
    )
    db.session.add(movement)
    db.session.commit()
    return jsonify(material=material.to_dict(), movement=movement.to_dict()), 201

"""Adhoc clients (kohal, 2026-10-30: "now we have to implement something called adhoc clients in client tab...
there will only be supply of extinguisher and refilling of extinguisher as service. single choice... once the
client is added, its respective adhoc project should also be added... primary key will be client's contact
number and should have option to select new or existing adhoc client").

An adhoc client is someone who buys extinguishers or has them refilled now and then - not a lead that was won
and fitted out. They live in their own list on the Clients tab (Client.is_adhoc) and are told apart by their
contact number, so adding an order for a number that's already there means picking the existing client.

Every order is one adhoc project for that client, filed under one of two services (constants.ADHOC_SERVICES):
- Refilling of FE: per line the FE type, weight, quantity, rate and the refilling, HPT and expiry dates, plus a
  remark.
- Supply of FE and Retail sale: per line the FE type or fire material, weight/spec, quantity and rate.
The project's value is the total of quantity x rate over its lines, so its Payment tab works like any other
project's. Its lines can be edited, and more added, afterwards."""

from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, g, jsonify, request
from sqlalchemy import func

from .auth import visible_clients, visible_projects
from .constants import ADHOC_SERVICES
from .extensions import db
from .models import AdhocItem, Client, Project, Service, settings_for_client
from .modules import has_module
from .timeutil import today_local
from .validation import Fields, api_errors

bp = Blueprint("adhoc", __name__)
api_errors(bp)

SERVICE_BY_KEY = {key: (label, service_name) for key, label, service_name in ADHOC_SERVICES}
MAX_ITEMS = 100
MAX_QTY = 100_000
MAX_RATE = Decimal("10000000")


@bp.before_request
def _adhoc_access():
    # Anyone who works with clients or with projects - the order form lives on Clients, the items on a project.
    if not (has_module(g.user, "clients") or has_module(g.user, "projects")):
        abort(403, "You don't have access to this.")


def _digits(phone) -> str:
    """The last 10 digits of a phone number (+91, 0, spaces and dashes don't matter) - '' if it isn't a plausible
    10-digit mobile number. Same rule as clients._phone_userid."""
    import re
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) > 10:
        digits = digits[-10:]
    return digits if len(digits) == 10 else ""


def _adhoc_client_by_phone(digits: str):
    """The adhoc client with this contact number, if any - looked up over every adhoc client rather than in the
    database, since the number is stored encrypted."""
    for c in Client.query.filter_by(is_adhoc=True).all():
        if _digits(c.phone) == digits:
            return c
    return None


def _service_for(key):
    label, service_name = SERVICE_BY_KEY[key]
    service = Service.query.filter(func.lower(Service.name) == service_name.lower()).first()
    if service is None:
        service = Service(name=service_name)
        db.session.add(service)
        db.session.flush()
    return service


def _clean_items(raw, kind):
    """The order's lines, checked. Returns (items, errors) - errors keyed 'items' for the whole list or
    'items.<n>.<field>' for one box, so the form can put each message under the right field."""
    errors = {}
    if not isinstance(raw, list) or not raw:
        return [], {"items": "Add at least one item"}
    if len(raw) > MAX_ITEMS:
        return [], {"items": f"At most {MAX_ITEMS} items in one order"}
    items = []
    for n, row in enumerate(raw):
        row = row if isinstance(row, dict) else {}
        f = Fields(row)
        f.text("fe_type", 120, required=True, label="the FE type" if kind == "refilling" else "the FE type or fire material")
        f.text("weight", 60, required=True, label="the weight" if kind == "refilling" else "the weight or spec")
        f.text("remark", 400)
        for key, message in f.errors.items():
            errors[f"items.{n}.{key}"] = message
        try:
            qty = int(str(row.get("qty")).strip())
            if not 1 <= qty <= MAX_QTY:
                raise ValueError
        except (TypeError, ValueError):
            errors[f"items.{n}.qty"] = f"Enter a whole number from 1 to {MAX_QTY}"
            qty = None
        try:
            rate = Decimal(str(row.get("rate")).strip())
            if not rate.is_finite() or rate < 0 or rate > MAX_RATE:
                raise InvalidOperation
            rate = rate.quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            errors[f"items.{n}.rate"] = "Enter the rate as a number"
            rate = None
        item = {"fe_type": f.data.get("fe_type", ""), "weight": f.data.get("weight", ""), "qty": qty, "rate": rate,
                "remark": f.data.get("remark", ""), "refill_date": None, "hpt_date": None, "expiry_date": None}
        if kind == "refilling":
            # Every box but the remark is required (kohal, 2026-10-30: "these should also be mandatory").
            for key in ("refill_date", "hpt_date", "expiry_date"):
                raw_date = row.get(key)
                if raw_date in (None, ""):
                    errors[f"items.{n}.{key}"] = "This field is required"
                    continue
                try:
                    item[key] = date.fromisoformat(str(raw_date))
                except ValueError:
                    errors[f"items.{n}.{key}"] = "Pick a valid date"
            if item["refill_date"] and item["expiry_date"] and item["expiry_date"] < item["refill_date"]:
                errors[f"items.{n}.expiry_date"] = "The expiry date can't be before the refilling date"
        items.append(item)
    return items, errors


def _fill(project, items):
    """Replace a project's lines and bring its value in line with them."""
    project.adhoc_items = [AdhocItem(position=i, **item) for i, item in enumerate(items, start=1)]
    project.estimated_amount = sum((item["qty"] * item["rate"] for item in items), Decimal("0")).quantize(Decimal("0.01"))


def _adhoc_kind(project):
    """'refilling' or 'supply' - which of the two services this adhoc project is filed under."""
    names = {s.name.lower() for s in project.services}
    for key, _label, service_name in ADHOC_SERVICES:
        if service_name.lower() in names:
            return key
    return "supply"


@bp.get("/api/adhoc/clients")
def list_adhoc_clients():
    """Every adhoc client, for choosing an existing one by name or contact number."""
    rows = Client.query.filter_by(is_adhoc=True).order_by(Client.name).all()
    return jsonify(clients=[{"id": c.id, "name": c.name, "phone": _digits(c.phone) or c.phone, "address": c.address,
                              "orders": len(c.projects)} for c in rows],
                   services=[{"key": k, "label": label} for k, label, _ in ADHOC_SERVICES])


@bp.post("/api/adhoc/orders")
def create_order():
    """A new order: for a brand-new adhoc client (name, address, contact number) or an existing one (client_id).
    Creates the client when it is new, plus the adhoc project with its lines."""
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    errors = {}

    service_key = payload.get("service")
    if service_key not in SERVICE_BY_KEY:
        errors["service"] = "Choose supply or refilling"
    items, item_errors = _clean_items(payload.get("items"), service_key if service_key in SERVICE_BY_KEY else "supply")
    errors.update(item_errors)

    client = None
    raw_id = payload.get("client_id")
    if raw_id not in (None, ""):
        try:
            client = visible_clients().filter(Client.id == int(raw_id), Client.is_adhoc.is_(True)).first()
        except (TypeError, ValueError):
            client = None
        if client is None:
            errors["client_id"] = "Choose an adhoc client from the list"
    else:
        f = Fields(payload)
        f.text("name", 160, required=True, label="the client's name")
        f.text("address", 400, required=True, label="the address")
        f.text("phone", 40, required=True, label="the contact number")
        errors.update(f.errors)
        digits = _digits(f.data.get("phone"))
        if "phone" not in errors:
            if not digits:
                errors["phone"] = "Enter a 10-digit contact number"
            elif _adhoc_client_by_phone(digits) is not None:
                errors["phone"] = "There is already an adhoc client with this contact number - choose them as an existing client"
        if not errors:
            client = Client(name=f.data["name"], address=f.data["address"], phone=digits, is_adhoc=True, owner_code=g.user.code)
            db.session.add(client)

    if errors:
        db.session.rollback()
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    label, _service_name = SERVICE_BY_KEY[service_key]
    project = Project(
        client=client, title=f"{label} · {today_local().strftime('%d %b %Y')}", site_name=client.name,
        site_address=client.address, status="running", owner_code=g.user.code,
        work_category=_service_name, services=[_service_for(service_key)],
    )
    _fill(project, items)
    db.session.add(project)
    db.session.commit()
    return jsonify(client_id=client.id, project_id=project.id), 201


@bp.put("/api/adhoc/projects/<int:project_id>/items")
def replace_items(project_id):
    """Change the lines of an adhoc project (edit, remove, add more) - the project's value follows."""
    project = visible_projects().filter(Project.id == project_id).first()
    if project is None or not project.client.is_adhoc:
        abort(404)
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    items, errors = _clean_items(payload.get("items"), _adhoc_kind(project))
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    _fill(project, items)
    db.session.commit()
    return jsonify(items=[i.to_dict() for i in project.adhoc_items], estimated_amount=float(project.estimated_amount),
                   kind=_adhoc_kind(project), currency=settings_for_client()["currency"])

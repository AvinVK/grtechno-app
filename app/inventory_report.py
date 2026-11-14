"""Inventory report (kohal, 2026-11-14: "in me tab in inventory block, i want to see inventory report", then "have inventory report as a subtab in reports
block in me tab", then: "inside this one inventory report, there should be 3 sub report (in excel 3 sheets). first, have from date and to date -
1. per day stock in (from to date) 2. per day stock out i.e, assigned to project - allocation (from to date) 3. at any selected date whats the inventory
status - also have material search for point 1 and 2").

Three reports, all rebuilt from the stock ledger (MaterialMovement, approved rows only - a pending or rejected request never moved stock):
  1. Stock in: every purchase or receipt between two dates, day by day (a stock-in with no project - a return from a project is not a purchase).
  2. Stock out: every issue to a project between two dates, day by day, with anything a project sent back shown against it as a minus, valued at the
     stock's own cost - the same figures a project's Materials tab shows.
  3. Inventory status: what was in stock at the end of a chosen day and what it was worth - worked out by replaying the ledger up to that day, the same way
     Inventory itself keeps a material's quantity and average cost. For today it also lists what is short for the project requests waiting on it.
Reports 1 and 2 can be narrowed to one material. It is the Inventory subtab of the Reports page (app/reports.py, app/static/js/reports.js), whose Excel
download has one sheet for each report (see sheets())."""

from datetime import date
from decimal import Decimal

from flask import Blueprint, abort, jsonify, redirect, request

from .extensions import db
from .inventory import _restock_rows
from .models import Material, MaterialMovement, settings_for_client
from .modules import check_module
from .timeutil import today_local
from .validation import api_errors

bp = Blueprint("inventory_report", __name__)
api_errors(bp)

ZERO = Decimal("0")
MAX_DAYS = 740                  # the longest range one report covers - about two years


@bp.before_request
def _inventory_service():
    check_module("inventory")


def _f(value) -> float:
    return float(Decimal(value).quantize(Decimal("0.01")))


def _day(raw, default, what):
    if not raw:
        return default
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        abort(422, f"Pick a valid {what}")


def parse_args(args):
    """(from, to, as on, material id) from the request - the dates default to this month so far and today; a bad one is a 422, not a guess."""
    today = today_local()
    start = _day(args.get("from"), today.replace(day=1), "from date")
    end = _day(args.get("to"), today, "to date")
    as_on = _day(args.get("as_on"), today, "date")
    if start > end:
        abort(422, "The from date is after the to date")
    if end > today or as_on > today:
        abort(422, "That day hasn't happened yet")
    if (end - start).days > MAX_DAYS:
        abort(422, "Pick a range of two years or less")
    material_id = args.get("material_id", type=int)
    if material_id is not None and db.session.get(Material, material_id) is None:
        abort(422, "Pick a material from the list")
    return start, end, as_on, material_id


def _in_range(query, start, end, material_id):
    query = query.filter(MaterialMovement.status == "approved", MaterialMovement.entry_date >= start, MaterialMovement.entry_date <= end)
    return query.filter(MaterialMovement.material_id == material_id) if material_id else query


def _days(entries, key):
    """Entries grouped by day, oldest first, each day with its total."""
    days = {}
    for e in entries:
        d = days.setdefault(e["date"], {"date": e["date"], "total": ZERO, "entries": []})
        d["entries"].append(e)
        d["total"] += Decimal(str(e[key]))
    return [{**d, "total": _f(d["total"])} for d in days.values()]


def stock_in(start, end, material_id=None) -> dict:
    moves = (_in_range(MaterialMovement.query.filter(MaterialMovement.kind == "in", MaterialMovement.project_id.is_(None)), start, end, material_id)
             .order_by(MaterialMovement.entry_date, MaterialMovement.id).all())
    entries = [{"date": mv.entry_date.isoformat(), "code": mv.material.code, "name": mv.material.name, "unit": mv.material.unit,
                "quantity": _f(mv.quantity), "rate": _f(mv.rate), "amount": _f(mv.amount), "gst": _f(mv.gst_amount), "total": _f(mv.total_cost or mv.amount),
                "supplier": mv.supplier.name if mv.supplier else "", "bill_no": mv.bill_no} for mv in moves]
    return {"days": _days(entries, "total"), "entries": entries, "count": len(entries),
            "amount": _f(sum((Decimal(str(e["amount"])) for e in entries), ZERO)), "gst": _f(sum((Decimal(str(e["gst"])) for e in entries), ZERO)),
            "total": _f(sum((Decimal(str(e["total"])) for e in entries), ZERO))}


def stock_out(start, end, material_id=None) -> dict:
    """Issues to projects, with returns from them as minus rows - so a day's total and the grand total are what was really allocated."""
    moves = (_in_range(MaterialMovement.query.filter(MaterialMovement.kind.in_(("out", "in"))), start, end, material_id)
             .order_by(MaterialMovement.entry_date, MaterialMovement.id).all())
    entries = []
    for mv in moves:
        if mv.kind == "in" and mv.project_id is None:               # a purchase, not a return
            continue
        sign = 1 if mv.kind == "out" else -1
        entries.append({"date": mv.entry_date.isoformat(), "kind": "Issued" if mv.kind == "out" else "Returned",
                        "project_code": mv.project.code if mv.project else "", "project": mv.project.title if mv.project else "Removed project",
                        "code": mv.material.code, "name": mv.material.name, "unit": mv.material.unit,
                        "quantity": _f(sign * mv.quantity), "rate": _f(mv.rate), "amount": _f(sign * mv.amount),
                        "given_by": mv.given_by.name if mv.given_by else ""})
    return {"days": _days(entries, "amount"), "entries": entries, "count": len(entries),
            "total": _f(sum((Decimal(str(e["amount"])) for e in entries), ZERO))}


def status_at(day) -> dict:
    """What was in stock at the end of `day`: the ledger replayed up to then in the order Inventory itself replays it (app/inventory.py
    _recompute_material) - a purchase blends its rate into the average cost, an issue draws down at the average."""
    moves = (MaterialMovement.query.filter(MaterialMovement.status == "approved", MaterialMovement.entry_date <= day)
             .order_by(MaterialMovement.entry_date, MaterialMovement.approved_at, MaterialMovement.id).all())
    state = {}
    for mv in moves:
        s = state.setdefault(mv.material_id, {"material": mv.material, "qty": ZERO, "rate": ZERO})
        if mv.kind == "in":
            new_qty = s["qty"] + mv.quantity
            if new_qty > 0:
                s["rate"] = (((s["qty"] * s["rate"]) + (mv.quantity * mv.rate)) / new_qty).quantize(Decimal("0.01"))
            s["qty"] = new_qty
        else:
            s["qty"] -= mv.quantity
    rows = []
    for s in state.values():
        m = s["material"]
        value = (s["qty"] * s["rate"]).quantize(Decimal("0.01")) if s["qty"] > 0 else ZERO
        rows.append({"material_id": m.id, "code": m.code, "name": m.name, "unit": m.unit, "quantity": _f(max(s["qty"], ZERO)), "rate": _f(s["rate"]),
                     "value": _f(value), "status": "In stock" if s["qty"] > 0 else "Out of stock"})
    rows.sort(key=lambda r: (r["status"] != "In stock", -r["value"], r["name"].lower()))
    short = []
    if day == today_local():                                         # what is waiting on stock only means something for today
        short = [{"code": r["material_code"], "name": r["material_name"], "unit": r["unit"], "in_stock": r["stock_qty"], "requested": r["requested_qty"],
                  "short_by": r["restock_qty"], "projects": [p["project_title"] or "" for p in r["projects"]]} for r in _restock_rows()]
    return {"date": day.isoformat(), "rows": rows, "total": _f(sum((Decimal(str(r["value"])) for r in rows), ZERO)), "short": short}


def _materials():
    return [{"value": m.id, "label": f"{m.name} ({m.code})"} for m in Material.query.order_by(Material.name).all()]


@bp.get("/inventory-report")
def page():
    return redirect("/reports#inventory")                  # it used to be a page of its own - old bookmarks still land on it


@bp.get("/api/inventory/report")
def report():
    """One part of the report: part=in, out or status."""
    start, end, as_on, material_id = parse_args(request.args)
    part = request.args.get("part", "in")
    if part not in ("in", "out", "status"):
        abort(422, "Pick stock in, stock out or inventory status")
    body = stock_in(start, end, material_id) if part == "in" else stock_out(start, end, material_id) if part == "out" else status_at(as_on)
    return jsonify(part=part, report=body, materials=_materials(), currency=settings_for_client()["currency"],
                   **{"from": start.isoformat(), "to": end.isoformat(), "as_on": as_on.isoformat(), "material_id": material_id})


def sheets(args) -> list:
    """The three reports as workbook sheets (see app/xlsx.py) - what the Reports page downloads, for the dates and material picked."""
    start, end, as_on, material_id = parse_args(args)
    cur = settings_for_client()["currency"]
    shown = lambda d: d.strftime("%d %b %Y")                    # noqa: E731

    def sheet(name, header, body, total=None):
        rows = [header] + body + ([total] if total else [])
        return {"name": name, "freeze": 1, "bold_rows": {0, len(rows) - 1} if total else {0}, "filter": True, "rows": rows}

    s_in = stock_in(start, end, material_id)
    s_out = stock_out(start, end, material_id)
    status = status_at(as_on)
    return [
        sheet("Stock in", ["Date", "Material", "Code", "Unit", "Quantity", f"Rate ({cur})", f"Amount before GST ({cur})", f"GST ({cur})", f"Total cost ({cur})", "Supplier", "Bill no"],
              [[e["date"], e["name"], e["code"], e["unit"], e["quantity"], e["rate"], e["amount"], e["gst"], e["total"], e["supplier"], e["bill_no"]] for e in s_in["entries"]],
              ["Total", None, None, None, None, None, s_in["amount"], s_in["gst"], s_in["total"], None, None] if s_in["entries"] else None),
        sheet("Stock out", ["Date", "Issued / returned", "Project", "Title", "Material", "Code", "Unit", "Quantity", f"Rate ({cur})", f"Amount ({cur})", "Given by"],
              [[e["date"], e["kind"], e["project_code"], e["project"], e["name"], e["code"], e["unit"], e["quantity"], e["rate"], e["amount"], e["given_by"]] for e in s_out["entries"]],
              ["Total", None, None, None, None, None, None, None, None, s_out["total"], None] if s_out["entries"] else None),
        sheet("Inventory status", ["Material", "Code", "Unit", "Status", f"Quantity on {shown(as_on)}", f"Average cost ({cur})", f"Value on {shown(as_on)} ({cur})"],
              [[r["name"], r["code"], r["unit"], r["status"], r["quantity"], r["rate"], r["value"]] for r in status["rows"]],
              ["Total", None, None, None, None, None, status["total"]] if status["rows"] else None),
    ]


def filename(args) -> str:
    start, end, _as_on, _material = parse_args(args)
    return f"inventory-report-{start.isoformat()}-to-{end.isoformat()}.xlsx"

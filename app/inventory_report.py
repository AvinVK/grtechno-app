"""Inventory report (kohal, 2026-11-14: "in me tab in inventory block, i want to see inventory report. in that it will have monthly reports of
total stock in, stocks allocated to projects" - and, asked what else: stock value now, a low-stock list, and an Excel download).

One month at a time, rebuilt from the stock ledger (MaterialMovement, approved rows only - a pending or rejected request never moved stock):
  - Stock in: what was bought that month, per material (a stock-in with no project - a return from a project is not a purchase).
  - Allocated to projects: what went out to each project that month, less anything it sent back, valued at the stock's own cost - the same
    figures a project's Materials tab shows.
  - Stock value now: what is in stock today and what it is worth. A snapshot of today, not of the month's end, since the ledger keeps a running
    balance rather than a balance per month.
  - Low stock: materials that cannot cover the project requests waiting on them (Inventory's own restock list), and ones that have run out.
It is the Inventory subtab of the Reports page (app/reports.py, app/static/js/reports.js - kohal, 2026-11-14: "have inventory report as a subtab in
reports block in me tab"): the figures below are shown there, and its Excel download is built from sheets()."""

import calendar
from datetime import date
from decimal import Decimal

from flask import Blueprint, jsonify, redirect, request

from .extensions import db
from .inventory import _restock_rows
from .models import Material, MaterialMovement, settings_for_client
from .modules import check_module
from .reports import _month_label, _month_or_default
from .timeutil import today_local
from .validation import api_errors

bp = Blueprint("inventory_report", __name__)
api_errors(bp)

ZERO = Decimal("0")


@bp.before_request
def _inventory_service():
    check_module("inventory")


def _months():
    """This month and the 23 before it, newest first - the same list the Reports page offers."""
    today = today_local()
    out, y, m = [], today.year, today.month
    for _ in range(24):
        out.append({"value": f"{y}-{m:02d}", "label": _month_label(y, m)})
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


def _f(value) -> float:
    return float(Decimal(value).quantize(Decimal("0.01")))


def build_report(year: int, month: int) -> dict:
    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    moves = (MaterialMovement.query.filter_by(status="approved")
             .filter(MaterialMovement.entry_date >= first, MaterialMovement.entry_date <= last).all())

    bought, allocated = {}, {}
    for mv in moves:
        if mv.kind == "in" and mv.project_id is None:                       # a purchase or receipt
            b = bought.setdefault(mv.material_id, {"material": mv.material, "qty": ZERO, "amount": ZERO, "gst": ZERO, "total": ZERO, "entries": 0})
            b["qty"] += mv.quantity
            b["amount"] += mv.amount
            b["gst"] += mv.gst_amount
            b["total"] += mv.total_cost or mv.amount
            b["entries"] += 1
        elif mv.kind in ("out", "in"):                                      # issued to a project, or sent back from it
            sign = 1 if mv.kind == "out" else -1
            p = allocated.setdefault(mv.project_id, {"project": mv.project, "amount": ZERO, "materials": {}})
            m = p["materials"].setdefault(mv.material_id, {"material": mv.material, "qty": ZERO, "amount": ZERO})
            m["qty"] += sign * mv.quantity
            m["amount"] += sign * mv.amount
            p["amount"] += sign * mv.amount

    stock_in = [{"material_id": b["material"].id, "code": b["material"].code, "name": b["material"].name, "unit": b["material"].unit,
                 "quantity": _f(b["qty"]), "amount": _f(b["amount"]), "gst": _f(b["gst"]), "total": _f(b["total"]), "entries": b["entries"]}
                for b in bought.values()]
    stock_in.sort(key=lambda r: r["name"].lower())

    projects = []
    for p in allocated.values():
        materials = [{"code": m["material"].code, "name": m["material"].name, "unit": m["material"].unit, "quantity": _f(m["qty"]), "amount": _f(m["amount"])}
                     for m in p["materials"].values() if m["qty"] != 0 or m["amount"] != 0]
        if not materials:
            continue
        materials.sort(key=lambda r: r["name"].lower())
        project = p["project"]
        projects.append({"project_id": project.id if project else None, "code": project.code if project else "",
                         "title": project.title if project else "Removed project", "amount": _f(p["amount"]), "materials": materials})
    projects.sort(key=lambda r: (-r["amount"], r["title"].lower()))

    in_stock = [m for m in Material.query.filter_by(is_active=True).order_by(Material.name).all() if m.stock_qty > 0]
    stock = [{"material_id": m.id, "code": m.code, "name": m.name, "unit": m.unit, "quantity": _f(m.stock_qty), "rate": _f(m.avg_rate), "value": _f(m.stock_value)}
             for m in in_stock]
    stock.sort(key=lambda r: (-r["value"], r["name"].lower()))

    short = [{"material_id": r["material_id"], "code": r["material_code"], "name": r["material_name"], "unit": r["unit"], "in_stock": r["stock_qty"],
              "requested": r["requested_qty"], "short_by": r["restock_qty"], "projects": [p["project_title"] or "" for p in r["projects"]]}
             for r in _restock_rows()]
    short_ids = {r["material_id"] for r in short}
    had_stock = {row[0] for row in db.session.query(MaterialMovement.material_id).filter_by(kind="in", status="approved").distinct()}
    out_of_stock = [{"material_id": m.id, "code": m.code, "name": m.name, "unit": m.unit}
                    for m in Material.query.filter_by(is_active=True).order_by(Material.name).all()
                    if m.stock_qty <= 0 and m.id in had_stock and m.id not in short_ids]

    return {
        "month": f"{year}-{month:02d}", "label": _month_label(year, month),
        "stock_in": {"rows": stock_in, "total": _f(sum((b["total"] for b in bought.values()), ZERO)),
                     "entries": sum(b["entries"] for b in bought.values())},
        "allocated": {"projects": projects, "total": _f(sum((Decimal(str(p["amount"])) for p in projects), ZERO))},
        "stock": {"rows": stock, "total": _f(sum((Decimal(str(r["value"])) for r in stock), ZERO))},
        "low": {"short": short, "out": out_of_stock},
    }


@bp.get("/inventory-report")
def page():
    return redirect("/reports#inventory")                  # it used to be a page of its own - old bookmarks still land on it


@bp.get("/api/inventory/report")
def report():
    year, month = _month_or_default(request.args.get("month"))
    months = _months()
    return jsonify(**build_report(year, month), months=months, current=months[0]["value"], currency=settings_for_client()["currency"])


def sheets(year: int, month: int) -> list:
    """The month's report as workbook sheets (see app/xlsx.py) - what the Reports page downloads."""
    r = build_report(year, month)
    cur = settings_for_client()["currency"]

    def sheet(name, header, body):
        return {"name": name, "freeze": 1, "bold_rows": {0}, "filter": True, "rows": [header] + body}

    summary = [["Inventory report", None], ["Month", r["label"]], ["Generated", today_local()], [None, None],
               [f"Stock in, incl. GST ({cur})", r["stock_in"]["total"]], [f"Allocated to projects, after returns ({cur})", r["allocated"]["total"]],
               [f"Stock value now ({cur})", r["stock"]["total"]]]
    sheets_ = [
        {"name": "Summary", "rows": summary, "bold_rows": {0}},
        sheet("Stock in", ["Material", "Code", "Unit", "Quantity", f"Cost before GST ({cur})", f"GST ({cur})", f"Total cost ({cur})", "Purchases"],
              [[x["name"], x["code"], x["unit"], x["quantity"], x["amount"], x["gst"], x["total"], x["entries"]] for x in r["stock_in"]["rows"]]),
        sheet("Allocated to projects", ["Project", "Title", "Material", "Unit", "Quantity (after returns)", f"Amount ({cur})"],
              [[p["code"], p["title"], m["name"], m["unit"], m["quantity"], m["amount"]] for p in r["allocated"]["projects"] for m in p["materials"]]),
        sheet("Stock now", ["Material", "Code", "Unit", "In stock", f"Average cost ({cur})", f"Value ({cur})"],
              [[x["name"], x["code"], x["unit"], x["quantity"], x["rate"], x["value"]] for x in r["stock"]["rows"]]),
        sheet("Low stock", ["Material", "Code", "Unit", "Status", "In stock", "Asked for by projects", "Short by", "Projects waiting"],
              [[x["name"], x["code"], x["unit"], "Short for pending requests", x["in_stock"], x["requested"], x["short_by"], ", ".join(x["projects"])] for x in r["low"]["short"]]
              + [[x["name"], x["code"], x["unit"], "Out of stock", 0, None, None, ""] for x in r["low"]["out"]]),
    ]
    return sheets_

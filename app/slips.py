"""Salary slips (kohal, 2026-11-10: "in payroll sheet, have a Release salary button. once clicked, it should show the same payroll sheet to
the employee the salary was released. also, have a vertical salary slip instead of horizontal when showing the slip to the employee.
have them downloadable as well").

The admin releases one employee's row of the payment sheet - a month for a salaried employee, a 2-week pay period for a daily-wage /
contractor one - or every row at once. Releasing keeps a copy of the figures as they were (the employee's slip does not shift if
attendance or an advance is changed afterwards; the sheet says "Changed since release" and the admin can release again, or withdraw it).
The employee opens it from the Me hub's "Salary slips" as a vertical slip and can download it as a PDF; the admin can download the same
PDF for any row of the sheet, released or not.

The slip is built from the same row as the sheet (app/payroll.py's payment_sheet / payment_sheet_daily), so the two always agree."""

import json
import re
from datetime import date
from decimal import Decimal

from flask import Blueprint, Response, abort, g, jsonify, render_template, request

from .extensions import db
from .models import SalarySlip, Worker, settings_for_client, utcnow
from .modules import check_module
from .payroll import PAYROLL_START, payment_sheet, payment_sheet_daily
from .pdf import Page, build_pdf
from .timeutil import to_local, today_local
from .validation import api_errors

bp = Blueprint("slips", __name__)
api_errors(bp)

KIND_LABEL = {"daily_wages": "Daily wages", "contractor": "Contractor", "regular": "Salaried"}


def _admin_only():
    check_module("workforce")
    if not g.user.is_admin:
        abort(403, "Only the admin releases salary slips.")


# ---------- what is on the slip ----------

def _row(label, value, kind="money", strong=False):
    return {"label": label, "value": value, "type": kind, "strong": strong}


def slip_view(snap: dict, released_on=None) -> dict:
    """The slip as sections of label / value rows - what the app draws and the PDF prints - from a stored (or live) snapshot."""
    r, daily = snap["row"], snap["kind"] == "daily"
    if daily:
        attendance = [_row("Days in period", r["days_in_period"], "num"), _row("Present days", r["present"], "num"),
                      _row("Paid holidays", r["holidays"], "num"), _row("Absent days", r["absent"], "num")]
        earnings = [_row("Daily wage", r["wage"]), _row("Wages earned", r["earned"], strong=True)]
        net_label, net, paid, due = "Net payable", r["net"], r["paid"], r["due"]
    else:
        attendance = [_row("Total days of month", r["days_in_month"], "num"), _row("Present days (paid days)", r["present"], "num"),
                      _row("Absent days", r["absent"], "num"), _row("Sick leave", r["sick_leave"], "num"),
                      _row("Casual leave", r["casual_leave"], "num"), _row("Holidays", r["holidays"], "num"),
                      _row("Sick leave balance", r["sick_balance"], "num"), _row("Casual leave balance", r["casual_balance"], "num")]
        earnings = [_row("Monthly salary", r["salary"]), _row("Salary per day", r["per_day"]),
                    _row("Deduction for absences", r["deduction"]), _row("Month net salary", r["net"], strong=True),
                    _row("House rent / petrol", r["allowance"])]
        net_label, net, paid, due = "Net pay", r["gross"], r["paid"], r["salary_due"]
    sections = [{"title": "Attendance", "rows": attendance}, {"title": "Earnings", "rows": earnings},
                {"title": "Deductions", "rows": [_row("Advance deduction", r["advance_deduction"]), _row("Other deduction", r["other_deduction"])]}]
    if any(r[k] for k in ("old_advance", "advance_taken", "advance_total", "advance_balance")):
        sections.append({"title": "Advance account", "rows": [
            _row("Old advance balance", r["old_advance"]), _row("Advance taken", r["advance_taken"]),
            _row("Total advance due", r["advance_total"]), _row("Advance balance after this slip", r["advance_balance"])]})
    sections.append({"title": "Payment (as on the day it was released)" if released_on else "Payment",
                     "rows": [_row("Paid", paid), _row("Balance due", due, strong=True)]})
    return {"kind": snap["kind"], "label": snap["label"], "name": r["name"], "type_label": KIND_LABEL.get(snap.get("employment_type"), ""),
            "from": r["from"], "to": r["to"], "sections": sections, "net": {"label": net_label, "value": net}, "released_on": released_on}


# ---------- the PDF ----------

def _indian(value) -> str:
    """12,34,567.50 - lakh grouping, paise only when there are some."""
    n = Decimal(str(value)).quantize(Decimal("0.01"))
    neg, n = n < 0, abs(n)
    whole, paise = divmod(int(n * 100), 100)
    s = str(whole)
    if len(s) > 3:
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", s[:-3])
        s = f"{head},{s[-3:]}"
    return ("-" if neg else "") + s + (f".{paise:02d}" if paise else "")


def _show(row) -> str:
    v = row["value"]
    if row["type"] == "money":
        return f"Rs. {_indian(v)}"
    if row["type"] == "num":
        return f"{v:g}" if isinstance(v, (int, float)) else str(v)
    return str(v)


def _day(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d %b %Y")


def slip_pdf(view: dict, footer: str) -> bytes:
    """One A4 page: a coloured title band, who and which period, the sections, the net pay in a box, a small footer line."""
    page = Page()
    left, right = 40, page.width - 40
    page.rect(0, page.height - 78, page.width, 78, fill=(0.85, 0.22, 0.12))
    page.text(left, page.height - 38, "SALARY SLIP", size=21, bold=True, color=(1, 1, 1))
    page.text_right(right, page.height - 38, view["label"], size=14, bold=True, color=(1, 1, 1))
    page.text(left, page.height - 60, "Lead desk", size=10, color=(1, 0.9, 0.85))
    y = page.height - 112
    page.text(left, y, view["name"], size=16, bold=True)
    page.text_right(right, y, view["type_label"], size=11, color=(0.4, 0.4, 0.4))
    y -= 18
    page.text(left, y, f"Pay period: {_day(view['from'])} to {_day(view['to'])}", size=10, color=(0.35, 0.35, 0.35))
    y -= 22
    for section in view["sections"]:
        page.rect(left, y - 5, right - left, 19, fill=(0.93, 0.91, 0.87))
        page.text(left + 8, y, section["title"], size=10, bold=True, color=(0.3, 0.27, 0.22))
        y -= 21
        for row in section["rows"]:
            page.text(left + 8, y, row["label"], size=10, bold=row["strong"])
            page.text_right(right - 8, y, _show(row), size=10, bold=row["strong"])
            page.line(left, y - 5, right, y - 5, width=0.4)
            y -= 17
        y -= 9
    y -= 10
    net = _show({"value": view["net"]["value"], "type": "money"})
    page.rect(left, y - 12, right - left, 34, fill=(0.86, 0.94, 0.9), stroke=(0.12, 0.48, 0.37), stroke_width=1)
    page.text(left + 10, y, view["net"]["label"], size=13, bold=True, color=(0.08, 0.35, 0.27))
    page.text_right(right - 10, y, net, size=15, bold=True, color=(0.08, 0.35, 0.27))
    page.text(left, 34, footer, size=8, color=(0.5, 0.5, 0.5))
    return build_pdf([page], title=f"Salary slip - {view['name']} - {view['label']}")


def _pdf_response(view: dict, footer: str):
    who = re.sub(r"[^a-z0-9]+", "-", view["name"].lower()).strip("-") or "employee"
    when = re.sub(r"[^a-z0-9]+", "-", view["label"].lower()).strip("-")
    return Response(slip_pdf(view, footer), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="salary-slip-{who}-{when}.pdf"', "Cache-Control": "no-store"})


# ---------- the admin's side: release from the payment sheet ----------

def _period_arg(kind, raw):
    """The first day of the period asked for - the month for a salaried slip, the 1st / 16th for a daily-wage one."""
    today = today_local()
    if kind == "salaried":
        try:
            year, month = (int(x) for x in str(raw or "").split("-"))
            first = date(year, month, 1)
        except ValueError:
            abort(422, "Give the month as YYYY-MM")
        if first < PAYROLL_START or first > today.replace(day=1):
            abort(422, "Pick a month payroll covers")
        return first
    if kind == "daily":
        try:
            first = date.fromisoformat(str(raw or ""))
        except ValueError:
            abort(422, "Give the pay period as its first day, YYYY-MM-DD")
        if first.day not in (1, 16) or first < PAYROLL_START or first > date(today.year, today.month, 1 if today.day <= 15 else 16):
            abort(422, "Pick a pay period payroll covers")
        return first
    abort(422, "Choose salaried or daily wages")


def _sheet(kind, first, worker_id=None):
    return payment_sheet(first.year, first.month, worker_id) if kind == "salaried" else payment_sheet_daily(first, worker_id)


def _snapshot(kind, data, row):
    worker = db.session.get(Worker, row["id"])
    clean = {k: v for k, v in row.items() if k != "slip"}
    return {"kind": kind, "label": data["label"], "employment_type": worker.employment_type if worker else None,
            "currency": settings_for_client()["currency"], "row": clean}


def _payload():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    return payload


@bp.post("/api/payroll/slips")
def release():
    _admin_only()
    payload = _payload()
    kind = payload.get("kind")
    first = _period_arg(kind, payload.get("period"))
    worker_id = payload.get("worker_id")
    if worker_id is not None and (not isinstance(worker_id, int) or isinstance(worker_id, bool)):
        abort(422, "Choose an employee from the list")
    data = _sheet(kind, first, worker_id)
    if not data["rows"]:
        abort(422, "There is nothing to release for that employee in this period" if worker_id else "There is nothing to release in this period")
    existing = {s.worker_id: s for s in SalarySlip.query.filter_by(kind=kind, period_start=first)}
    for row in data["rows"]:
        snap = json.dumps(_snapshot(kind, data, row))
        slip = existing.get(row["id"])
        if slip is None:
            db.session.add(SalarySlip(worker_id=row["id"], kind=kind, period_start=first, label=data["label"], data=snap,
                                      released_by_code=g.user.code))
        else:                                              # released before: the figures are kept again as they are now
            slip.label, slip.data, slip.released_by_code = data["label"], snap, g.user.code
            slip.released_at = utcnow()
    db.session.commit()
    return jsonify(released=len(data["rows"])), 201


@bp.delete("/api/payroll/slips/<int:slip_id>")
def withdraw(slip_id: int):
    _admin_only()
    slip = db.session.get(SalarySlip, slip_id)
    if slip is None:
        abort(404, "That slip is already withdrawn")
    db.session.delete(slip)
    db.session.commit()
    return jsonify(ok=True)


@bp.get("/api/payroll/slips/pdf")
def preview_pdf():
    """The slip for one row of the sheet as it stands now, released or not - the admin's own download."""
    _admin_only()
    kind = request.args.get("kind")
    first = _period_arg(kind, request.args.get("period"))
    worker_id = request.args.get("worker_id", type=int)
    if worker_id is None:
        abort(422, "Choose an employee from the list")
    data = _sheet(kind, first, worker_id)
    if not data["rows"]:
        abort(404, "Nothing for that employee in this period")
    view = slip_view(_snapshot(kind, data, data["rows"][0]))
    return _pdf_response(view, f"Figures as on {today_local().strftime('%d %b %Y')}. Not yet released to the employee unless released from the payment sheet.")


# ---------- the employee's side ----------

def _own_worker():
    return Worker.query.filter_by(user_code=g.user.code).first()


def _slip_or_404(slip_id):
    slip = db.session.get(SalarySlip, slip_id)
    if slip is None or not (g.user.is_admin or (slip.worker is not None and slip.worker.user_code == g.user.code)):
        abort(404, "That salary slip is not available")
    return slip


def _released_on(slip) -> str:
    return to_local(slip.released_at).date().isoformat()


@bp.get("/salary-slips")
def page():
    return render_template("salary_slips.html")


@bp.get("/api/salary-slips")
def my_slips():
    worker = _own_worker()
    slips = []
    if worker is not None:
        rows = SalarySlip.query.filter_by(worker_id=worker.id).order_by(SalarySlip.period_start.desc(), SalarySlip.id.desc()).limit(120).all()
        for s in rows:
            view = slip_view(json.loads(s.data))
            slips.append({"id": s.id, "kind": s.kind, "label": s.label, "released_on": _released_on(s), "net": view["net"]["value"],
                          "net_label": view["net"]["label"]})
    return jsonify(slips=slips, currency=settings_for_client()["currency"], has_record=worker is not None)


@bp.get("/api/salary-slips/<int:slip_id>")
def one_slip(slip_id: int):
    slip = _slip_or_404(slip_id)
    return jsonify(slip=slip_view(json.loads(slip.data), _released_on(slip)), id=slip.id, currency=settings_for_client()["currency"])


@bp.get("/api/salary-slips/<int:slip_id>.pdf")
def one_slip_pdf(slip_id: int):
    slip = _slip_or_404(slip_id)
    released = _released_on(slip)
    return _pdf_response(slip_view(json.loads(slip.data), released), f"Released on {date.fromisoformat(released).strftime('%d %b %Y')}.")

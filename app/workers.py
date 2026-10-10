"""Employee management (admin only): field workers and office staff who don't sign in to the app, tracked
instead from the WhatsApp group each marks their attendance in. Grouped by role - the same roles table
Users & roles uses (minus 'admin') - rather than the old manpower/staff split (see Worker.category in
models.py for why that split still exists in the database but not here). Attendance itself still only
arrives through the WhatsApp import, but the admin can add someone ahead of the next import (so their
attendance has somewhere to land), edit their name or role, or remove someone who left.

Two pages under Manage share one script (people.js): "Employee management" (who's where, and the last
week at a glance) and "Attendance sheet" (everyone ranked by attendance, lowest first, with each person's
full day-by-day record). The older per-category JSON APIs (/api/workers, /api/staff) are kept as they
were - they still use category, not role_key, since Leads still relies on them (see app/api.py)."""

from datetime import date, timedelta

from flask import Blueprint, g, jsonify, redirect, render_template, request
from sqlalchemy import func
from werkzeug.exceptions import HTTPException, abort

from .constants import PAYMENT_MODES
from .extensions import db
from .models import Role, Worker, WorkerAttendance, WorkerPayment, settings_for_client
from .validation import Fields, parse_money

EMPLOYMENT_TYPES = ("regular", "daily_wages")

WINDOW_DAYS = 14           # how many days back the one-off WhatsApp import covers; shown next to each count
PERIOD_DAYS = 30           # the Attendance sheet looks back at most this far from the last day with data
WEEK_DAYS = 7              # the "last week" dots on Employee management
UNASSIGNED = "unassigned"  # the group key for a worker with no role_key yet

bp = Blueprint("workers", __name__, url_prefix="/api/workers")            # Manpower's JSON API
page_bp = Blueprint("workers_page", __name__)                             # the pages
staff_bp = Blueprint("staff", __name__, url_prefix="/api/staff")          # Staff's JSON API
workforce_bp = Blueprint("workforce", __name__, url_prefix="/api/workforce")   # what the two pages read


@bp.errorhandler(HTTPException)
@staff_bp.errorhandler(HTTPException)
@workforce_bp.errorhandler(HTTPException)
def json_error(err):
    return jsonify(error=err.description or err.name), err.code


@bp.before_request
@staff_bp.before_request
@workforce_bp.before_request
def admin_only():
    if not g.user or not g.user.is_admin:
        abort(403, "Only the admin can do this.")


@page_bp.before_request
def admin_only_page():
    if not g.user or not g.user.is_admin:
        abort(403, "Only the admin can open this page.")


@page_bp.get("/workforce")
def workforce_page():
    return render_template("people.html", mode="roster", page_title="Employee management")


@page_bp.get("/attendance-sheet")
def sheet_page():
    return render_template("people.html", mode="sheet", page_title="Attendance sheet")


# The separate Manpower list and Staff list pages were folded into Employee management; old links still land.
@page_bp.get("/workers")
def page():
    return redirect("/workforce#manpower")


@page_bp.get("/staff")
def staff_page():
    return redirect("/workforce#staff")


# ---------- per-category APIs (unchanged) ----------

def _summary(worker: Worker) -> dict:
    return {**worker.to_dict(), "days_present": len(worker.attendance), "window_days": WINDOW_DAYS}


def _list(category):
    workers = Worker.query.filter_by(category=category).order_by(Worker.name).all()
    return jsonify(workers=[_summary(w) for w in workers], window_days=WINDOW_DAYS)


def _detail(category, worker_id):
    worker = Worker.query.filter_by(id=worker_id, category=category).first()
    if worker is None:
        abort(404)
    return jsonify(worker=worker.to_dict(), attendance=[a.to_dict() for a in worker.attendance], window_days=WINDOW_DAYS)


@bp.get("")
def list_workers():
    return _list("manpower")


@bp.get("/<int:worker_id>")
def get_worker(worker_id):
    return _detail("manpower", worker_id)


@staff_bp.get("")
def list_staff():
    return _list("staff")


@staff_bp.get("/<int:worker_id>")
def get_staff(worker_id):
    return _detail("staff", worker_id)


# ---------- Employee management, and the Attendance sheet ----------

def _period():
    """The days the Attendance sheet counts: up to the last day any attendance was recorded (never past
    today), at most PERIOD_DAYS long. The data arrives through imports, not live, so "today" can be past
    the end of it; days after data_until are "no data yet", never absent. None when there is no data."""
    first, last = db.session.query(func.min(WorkerAttendance.work_date), func.max(WorkerAttendance.work_date)).one()
    if last is None:
        return None, None
    end = min(last, date.today())
    return (max(first, end - timedelta(days=PERIOD_DAYS - 1)), end), last


def _own_start(worker, start):
    """Nobody is counted absent from before they first turned up."""
    return max(start, worker.first_seen) if worker.first_seen else start


def _day_status(day, present, worker, data_until):
    if day in present:
        return "present"
    if data_until is None or day > data_until or (worker.first_seen and day < worker.first_seen):
        return "none"
    return "absent"


def _person_row(worker, period, data_until, today):
    present = {a.work_date for a in worker.attendance if a.status == "present"}
    latest = next((a for a in worker.attendance if a.status == "present"), None)   # attendance is newest first
    deployed = None
    if latest:
        deployed = {
            "date": latest.work_date.isoformat(), "project_code": latest.project.code if latest.project else None,
            "project_title": latest.project.title if latest.project else None,
            "map_url": (WorkerAttendance._map_url(latest.check_in_lat, latest.check_in_lng)
                        or WorkerAttendance._map_url(latest.check_out_lat, latest.check_out_lng)),
        }
    week = []
    for back in range(WEEK_DAYS - 1, -1, -1):
        day = today - timedelta(days=back)
        week.append({"date": day.isoformat(), "status": _day_status(day, present, worker, data_until)})

    days = present_days = 0
    if period:
        start, end = _own_start(worker, period[0]), period[1]
        days = max(0, (end - start).days + 1)
        present_days = sum(1 for d in present if start <= d <= end)
    return {"id": worker.id, "name": worker.name, "role_key": worker.role_key or UNASSIGNED, "deployed": deployed,
            "week": week, "present_days": present_days, "days": days}


@workforce_bp.get("")
def workforce():
    period, data_until = _period()
    today = date.today()
    workers = Worker.query.order_by(Worker.name).all()
    roles = {r.key: r.name for r in Role.query.filter(Role.key != "admin").order_by(Role.name)}
    groups = {}
    for w in workers:
        key = w.role_key if w.role_key in roles else UNASSIGNED
        groups.setdefault(key, []).append(_person_row(w, period, data_until, today))
    return jsonify(
        **groups, roles=roles,          # roles is a {key: name} object, not an array, so it's not mistaken
        today=today.isoformat(), data_until=data_until.isoformat() if data_until else None,  # for a group above
        period={"start": period[0].isoformat(), "end": period[1].isoformat()} if period else None,
    )


@workforce_bp.get("/<int:worker_id>")
def person(worker_id):
    worker = db.session.get(Worker, worker_id)
    if worker is None:
        abort(404)
    period, data_until = _period()
    own = None
    if period and _own_start(worker, period[0]) <= period[1]:
        own = {"start": _own_start(worker, period[0]).isoformat(), "end": period[1].isoformat()}
    records = [a.to_dict() for a in worker.attendance
               if own and own["start"] <= a.work_date.isoformat() <= own["end"]]
    roles = {r.key: r.name for r in Role.query.filter(Role.key != "admin").order_by(Role.name)}
    return jsonify(worker=worker.to_dict(detail=True), period=own, attendance=records, roles=roles,
                   payment_modes=PAYMENT_MODES, currency=settings_for_client()["currency"],
                   today=date.today().isoformat(), data_until=data_until.isoformat() if data_until else None)


def _payload():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    return payload


def _employee_fields(payload):
    """name, role_key and the full HR detail set - only the keys actually present in the request are
    checked or returned (same partial-update rule as Fields itself), so a PATCH that only sends
    {"payments": [...]} doesn't also have to resend the name, and doesn't blank it out either."""
    f = Fields(payload)
    f.text("name", 120, required=True, label="a name")
    f.integer("age", 14, 90)
    f.text("qualification", 160)
    f.text("experience", 200)
    f.text("skills", 400)
    f.text("phone", 40)
    f.date("joining_date")
    f.money("wage_amount")
    f.text("pf_number", 60)
    f.text("esic_number", 60)
    f.text("reference", 200)
    data, errors = f.data, f.errors

    if "role_key" in payload:
        raw_role = payload["role_key"]
        if raw_role in (None, "", UNASSIGNED):
            data["role_key"] = None
        elif db.session.get(Role, raw_role) is None or raw_role == "admin":
            errors["role_key"] = "Choose a role from the list"
        else:
            data["role_key"] = raw_role

    if "employment_type" in payload:
        raw = payload["employment_type"]
        if raw in (None, ""):
            data["employment_type"] = ""
        elif raw in EMPLOYMENT_TYPES:
            data["employment_type"] = raw
        else:
            errors["employment_type"] = "Choose regular or daily wages"

    return data, errors


@workforce_bp.post("")
def add_worker():
    """Add someone ahead of the next WhatsApp import, or someone who never comes up in it (e.g. a new
    hire). role_key is the same role list Users & roles uses - a label here, not a login or permission.
    The rest is the usual HR paperwork - all optional, filled in now or later from Edit."""
    data, errors = _employee_fields(_payload())
    if not data.get("name") and "name" not in errors:
        errors["name"] = "Enter a name"
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    worker = Worker(source="manual", **data)
    db.session.add(worker)
    db.session.commit()
    return jsonify(worker=worker.to_dict(detail=True)), 201


def _payments(raw, errors):
    """Check a salary/wages log from the request - same shape and the same check as a project's payment
    schedule (see projects.py's _payments). Returns a list of dicts, or None if it has problems."""
    if not isinstance(raw, list) or len(raw) > 60:
        errors["payments"] = "The payment log should be a list of up to 60 entries"
        return None
    rows = []
    for i, item in enumerate(raw, start=1):
        f = Fields(item if isinstance(item, dict) else {})
        f.text("label", 120, required=True, label="a name for each payment entry")
        f.date("due_date")
        f.date("paid_date")
        f.text("comments", 2000)
        if isinstance(item, dict) and item.get("mode") not in (None, "", *PAYMENT_MODES):
            f.errors["mode"] = "Choose one of the payment modes"
        problems = dict(f.errors)
        amount = parse_money(item.get("amount", 0) if isinstance(item, dict) else 0, problems, "amount")
        if problems:
            errors["payments"] = f"Payment entry {i}: {next(iter(problems.values()))}"
            return None
        rows.append({
            "label": f.data["label"], "amount": amount, "due_date": f.data.get("due_date"),
            "mode": (item.get("mode") or "") if isinstance(item, dict) else "",
            "paid_date": f.data.get("paid_date"), "comments": f.data.get("comments", ""),
        })
    return rows


@workforce_bp.patch("/<int:worker_id>")
def edit_worker(worker_id):
    """Change a person's details, role, or their whole salary/wages log (sent as one list, same as a
    project's payment schedule - see persistSteps in people.js)."""
    worker = db.session.get(Worker, worker_id)
    if worker is None:
        abort(404)
    payload = _payload()
    data, errors = _employee_fields(payload)
    payments = None
    if "payments" in payload:
        payments = _payments(payload["payments"], errors)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    for field, value in data.items():
        setattr(worker, field, value)
    if payments is not None:
        worker.payments = [
            WorkerPayment(label=p["label"], amount=p["amount"], due_date=p["due_date"], mode=p["mode"],
                          paid_date=p["paid_date"], comments=p["comments"], position=i)
            for i, p in enumerate(payments, start=1)
        ]
    db.session.commit()
    return jsonify(worker=worker.to_dict(detail=True))


@workforce_bp.delete("/<int:worker_id>")
def delete_worker(worker_id):
    """Removes the person and their attendance history. Leads/surveys they were ever picked as the
    enquired-by or surveyor on keep existing, just without that attribution (see models.py)."""
    worker = db.session.get(Worker, worker_id)
    if worker is None:
        abort(404)
    db.session.delete(worker)
    db.session.commit()
    return "", 204

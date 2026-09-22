"""Attendance (the Attendance service): everyone checks themselves in and out, once per day, optionally
against a running project. A location is required to check in - enforced here, not only by the screen,
so it cannot be skipped by calling the API directly. Admin and any sees_all role (Accounts) can see
everyone's; everyone else sees only their own."""

from datetime import date

from flask import Blueprint, g, jsonify, render_template, request
from werkzeug.exceptions import abort

from .auth import visible_attendance
from .extensions import db
from .models import Attendance, Project, User, utcnow
from .modules import check_module
from .validation import Fields, api_errors

bp = Blueprint("attendance", __name__)
api_errors(bp)


@bp.before_request
def _attendance_service():
    check_module("attendance")


def _open_projects():
    return Project.query.filter(Project.status.in_(["planned", "running"])).order_by(Project.title).all()


def _today_row():
    return Attendance.query.filter_by(user_code=g.user.code, work_date=date.today()).first()


def _coord(payload, name, low, high, errors):
    """A latitude/longitude from the browser's geolocation. Missing just means missing (check_in below
    turns that into "location is required") - this only rejects a value that is there but not a real
    coordinate."""
    if payload.get(name) in (None, ""):
        return None
    try:
        value = float(payload[name])
    except (TypeError, ValueError):
        errors[name] = "That location looks wrong"
        return None
    if not (low <= value <= high):
        errors[name] = "That location looks wrong"
        return None
    return value


@bp.get("/attendance")
def page():
    return render_template("attendance.html")


@bp.get("/api/attendance/state")
def state():
    """What the signed-in person needs to check in or out today, plus their own recent history."""
    today = _today_row()
    history = (visible_attendance().filter_by(user_code=g.user.code)
               .order_by(Attendance.work_date.desc()).limit(30).all())
    return jsonify(
        today=today.to_dict() if today else None,
        projects=[{"id": p.id, "title": p.title, "client_name": p.client.name} for p in _open_projects()],
        history=[a.to_dict() for a in history],
        can_see_team=g.user.sees_all,
    )


@bp.post("/api/attendance/check-in")
def check_in():
    if _today_row() is not None:
        return jsonify(error="You have already checked in today."), 409

    payload = request.get_json(silent=True) if request.is_json else {}
    if not isinstance(payload, dict):
        payload = {}
    f = Fields(payload)
    f.text("notes", 400)
    project = None
    raw_id = payload.get("project_id")
    if raw_id not in (None, ""):
        try:
            project = db.session.get(Project, int(raw_id))
        except (TypeError, ValueError):
            project = None
        if project is None:
            return jsonify(error="Check the highlighted fields", fields={"project_id": "Choose a project from the list"}), 422

    lat = _coord(payload, "lat", -90, 90, f.errors)
    lng = _coord(payload, "lng", -180, 180, f.errors)
    if (lat is None or lng is None) and "lat" not in f.errors and "lng" not in f.errors:
        f.errors["lat"] = "Turn on location and try again. Location is required to check in."
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422

    row = Attendance(
        user_code=g.user.code, work_date=date.today(), project_id=project.id if project else None,
        check_in_at=utcnow(), check_in_lat=lat, check_in_lng=lng, notes=f.data.get("notes", ""),
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(today=row.to_dict()), 201


@bp.post("/api/attendance/check-out")
def check_out():
    row = _today_row()
    if row is None:
        return jsonify(error="You have not checked in today."), 409
    if row.check_out_at is not None:
        return jsonify(error="You have already checked out today."), 409
    row.check_out_at = utcnow()
    db.session.commit()
    return jsonify(today=row.to_dict())


@bp.get("/api/attendance/team")
def team():
    """The full register, for admin and other sees_all roles. Filterable by date and, for a longer look,
    a date range; newest first."""
    if not g.user.sees_all:
        abort(403, "Only the admin or accounts can see everyone's attendance.")

    day = request.args.get("date")
    query = visible_attendance()
    if day:
        try:
            query = query.filter(Attendance.work_date == date.fromisoformat(day))
        except ValueError:
            abort(422, "Give the date as YYYY-MM-DD")
    rows = query.order_by(Attendance.work_date.desc(), Attendance.check_in_at.desc()).limit(500).all()
    return jsonify(
        records=[a.to_dict() for a in rows],
        users=[{"code": u.code, "name": u.name} for u in User.query.filter_by(is_active=True).order_by(User.name)],
    )

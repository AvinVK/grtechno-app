"""Attendance (the Attendance service): everyone checks themselves in and out, as many times a day as they
like (a lunch break, a second site), optionally against a running project. A location is required to check
in - enforced here, not only by the screen, so it cannot be skipped by calling the API directly - unless
REQUIRE_ATTENDANCE_LOCATION is switched off in a local .env (kohal, 2026-10-16: "just in dev", never set on
prod - see app/config.py). Admin and any sees_all role (Accounts) can see everyone's; everyone else sees
only their own."""

from datetime import date

from flask import Blueprint, current_app, g, jsonify, render_template, request
from werkzeug.exceptions import abort

from .auth import (
    EARLY_CHECKOUT_CUTOFF,
    PROJECT_MANAGER_ROLE_KEYS,
    attendance_restriction,
    can_approve_attendance,
    visible_attendance,
    _is_daily_wage,
)
from .extensions import db
from .models import AbsenceRequest, Attendance, Project, User, utcnow
from .modules import check_module, has_module
from .timeutil import today_local, to_local
from .validation import Fields, api_errors

bp = Blueprint("attendance", __name__)
api_errors(bp)


@bp.before_request
def _attendance_service():
    check_module("attendance")


def _open_projects():
    return Project.query.filter(Project.status.in_(["planned", "running"])).order_by(Project.title).all()


def _open_session():
    """The session the signed-in person is currently in, if any - across every day, not just today. A
    session left open past midnight (forgot to check out) must still block a new check-in the next day,
    rather than quietly starting a second one while the first is still "open" (kohal, 2026-10-15 - a
    forgotten Wed check-out was letting Thu check-in happen anyway)."""
    return (Attendance.query.filter_by(user_code=g.user.code, check_out_at=None)
            .order_by(Attendance.check_in_at.desc()).first())


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
    # An "Attendance register" subtab shows up here for anyone who can also see it (kohal, 2026-10-20:
    # "cant both be clubbed and shown as 2 subtabs? attendance register and today's attendance") - the
    # register itself still lives on the Attendance sheet page (app/workers.py) for its own direct URL and
    # a person's full day-by-day record, but its top list is folded into this page too, see attendance.js.
    can_see_workforce = has_module(g.user, "workforce")
    # The admin doesn't check in or out - their Attendance is the team register for a chosen day.
    if g.user.is_admin:
        return render_template("attendance.html", page_title="Team attendance", team_only=True, can_see_workforce=can_see_workforce)
    return render_template("attendance.html", page_title="Your attendance", team_only=False, can_see_workforce=can_see_workforce)


def _no_admin_check_ins():
    if g.user.is_admin:
        abort(403, "The admin doesn't check in or out.")


@bp.get("/api/attendance/state")
def state():
    """What the signed-in person needs to check in or out, plus today's sessions so far and their own
    recent history. `today` is the currently open session (null if none - whether they never checked in
    today, or already checked out and could check in again); `today_sessions` is every one of today's rows,
    open or closed, oldest first."""
    open_session = _open_session()
    today_sessions = (Attendance.query.filter_by(user_code=g.user.code, work_date=date.today())
                       .order_by(Attendance.check_in_at).all())
    history = (visible_attendance().filter_by(user_code=g.user.code)
               .order_by(Attendance.work_date.desc(), Attendance.check_in_at.desc()).limit(60).all())
    return jsonify(
        today=open_session.to_dict() if open_session else None,
        today_sessions=[a.to_dict() for a in today_sessions],
        projects=[
            {"id": p.id, "title": p.title, "client_name": p.client.name, "site_district": p.site_district}
            for p in _open_projects()
        ],
        history=[a.to_dict() for a in history],
        can_see_team=g.user.sees_all,
        location_required=current_app.config["REQUIRE_ATTENDANCE_LOCATION"],
        can_mark_absent=_is_daily_wage(g.user),
        my_absences=[a.to_dict() for a in AbsenceRequest.query.filter_by(user_code=g.user.code)
                     .order_by(AbsenceRequest.for_date.desc()).limit(10).all()],
    )


@bp.post("/api/attendance/check-in")
def check_in():
    _no_admin_check_ins()
    if _open_session() is not None:
        return jsonify(error="You are already checked in. Check out first."), 409

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
    # Without a project: office work (the default) or marketing work.
    work = payload.get("work") or "office"
    if work not in ("office", "marketing"):
        return jsonify(error="Check the highlighted fields", fields={"work": "Choose what you are working on"}), 422

    lat = _coord(payload, "lat", -90, 90, f.errors)
    lng = _coord(payload, "lng", -180, 180, f.errors)
    location_required = current_app.config["REQUIRE_ATTENDANCE_LOCATION"]
    if location_required and (lat is None or lng is None) and "lat" not in f.errors and "lng" not in f.errors:
        f.errors["lat"] = "Turn on location and try again. Location is required to check in."
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422

    check_in_at = utcnow()
    restriction = attendance_restriction(g.user, project, check_in_at)
    approved = can_approve_attendance(g.user, project, restriction)
    row = Attendance(
        user_code=g.user.code, work_date=date.today(), project_id=project.id if project else None,
        check_in_at=check_in_at, check_in_lat=lat, check_in_lng=lng, notes=f.data.get("notes", ""),
        work_kind="marketing" if work == "marketing" and project is None else "",
        status="approved" if approved else "pending",
        approved_by_code=g.user.code if approved else None,
        approved_at=utcnow() if approved else None,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(today=row.to_dict()), 201


@bp.post("/api/attendance/check-out")
def check_out():
    _no_admin_check_ins()
    row = _open_session()
    if row is None:
        return jsonify(error="You are not checked in."), 409
    row.check_out_at = utcnow()
    # An early checkout, for a daily-wage worker, needs its own sign-off even if the check-in itself was
    # already approved (kohal, 2026-10-19: "Early checkout approval required of project manager") - back to
    # pending, same approvers as any other pending record (not narrowed further, unlike a late check-in or a
    # different-project session - see auth.attendance_restriction).
    if _is_daily_wage(g.user) and to_local(row.check_out_at).time() < EARLY_CHECKOUT_CUTOFF:
        row.status = "pending"
        row.approved_by_code = None
        row.approved_at = None
    db.session.commit()
    return jsonify(today=row.to_dict())


@bp.get("/api/attendance/rejections")
def rejections():
    """Rejected records the signed-in person hasn't seen a popup about yet (kohal, 2026-10-20: "a popup as
    soon as attendance was rejected so that user knows") - oldest first, same convention as the
    announcements popup (app/me.py). Read by the popup in app/static/js/common.js, which runs on every
    signed-in page, not just Attendance - someone could be anywhere in the app when this fires."""
    rows = (Attendance.query.filter_by(user_code=g.user.code, status="rejected", rejection_seen_at=None)
            .order_by(Attendance.approved_at).all())
    return jsonify(rejections=[a.to_dict() for a in rows])


@bp.post("/api/attendance/<int:record_id>/dismiss-rejection")
def dismiss_rejection(record_id):
    row = db.session.get(Attendance, record_id)
    if row is None or row.user_code != g.user.code:
        return jsonify(error="Not found"), 404
    row.rejection_seen_at = utcnow()
    db.session.commit()
    return "", 204


@bp.delete("/api/attendance/<int:record_id>")
def delete_record(record_id):
    """Admin and other sees_all roles can remove a wrong or test record. Nobody else - a person deleting
    their own attendance would defeat the point of keeping one."""
    if not g.user.sees_all:
        abort(403, "Only the admin or the accountant can delete an attendance record.")
    row = db.session.get(Attendance, record_id)
    if row is None:
        abort(404, "Not found")
    db.session.delete(row)
    db.session.commit()
    return "", 204


def _restriction_dict(a):
    """a.to_dict() plus why it needs a stricter approver, if it does (auth.attendance_restriction) - 'late'
    or 'multi_project', so the approvals list can say so instead of leaving it a mystery."""
    d = a.to_dict()
    d["restriction"] = attendance_restriction(a.user, a.project, a.check_in_at, exclude_id=a.id)
    return d


@bp.get("/api/attendance/approvals")
def approvals():
    """Pending attendance records the signed-in person can act on right now (see auth.can_approve_attendance)
    - a project manager, a site supervisor currently checked in somewhere, the admin, or Company Director.
    Same shape as /api/me/material-approvals, which pulls from here too for the Me hub's own section."""
    pending = Attendance.query.filter_by(status="pending").order_by(Attendance.created_at).all()
    return jsonify(approvals=[
        _restriction_dict(a) for a in pending
        if can_approve_attendance(g.user, a.project, attendance_restriction(a.user, a.project, a.check_in_at, exclude_id=a.id))
    ])


def _approve_or_reject(record_id, status):
    row = db.session.get(Attendance, record_id)
    if row is None:
        abort(404)
    if row.status != "pending":
        abort(409, "This record isn't waiting for approval.")
    restriction = attendance_restriction(row.user, row.project, row.check_in_at, exclude_id=row.id)
    if not can_approve_attendance(g.user, row.project, restriction):
        abort(403, "Only this project's manager, a site supervisor currently checked in there, the admin or Company Director can act on this.")
    row.status = status
    row.approved_by_code = g.user.code
    row.approved_at = utcnow()
    db.session.commit()
    return jsonify(record=row.to_dict())


@bp.post("/api/attendance/<int:record_id>/approve")
def approve_record(record_id):
    return _approve_or_reject(record_id, "approved")


@bp.post("/api/attendance/<int:record_id>/reject")
def reject_record(record_id):
    return _approve_or_reject(record_id, "rejected")


@bp.get("/api/attendance/team")
def team():
    """The full register, for admin and other sees_all roles. Filterable by date and, for a longer look,
    a date range; newest first."""
    if not g.user.sees_all:
        abort(403, "Only the admin or the accountant can see everyone's attendance.")

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


# ---------- absence notices (kohal, 2026-10-19) ----------
#
# "For absent provide option within check in tab ... Absent should be inform 1 day before" - a daily-wage
# worker saying, ahead of time, that they won't be in on a future day. Never becomes an Attendance row
# itself (see AbsenceRequest's own docstring) - it's a separate heads-up, waiting for the admin or a project
# manager (company-wide; there's no project to scope this to, since it's not against any one site) to see
# and acknowledge.

def _can_see_absences(user) -> bool:
    return user.is_admin or user.role_key in PROJECT_MANAGER_ROLE_KEYS


@bp.get("/api/attendance/absences")
def list_absences():
    if not _can_see_absences(g.user):
        abort(403, "Only the admin or a project manager can see absence notices.")
    pending = AbsenceRequest.query.filter_by(status="pending").order_by(AbsenceRequest.for_date).all()
    return jsonify(absences=[a.to_dict() for a in pending])


@bp.post("/api/attendance/absences")
def request_absence():
    if not _is_daily_wage(g.user):
        abort(403, "Only a daily-wage worker can mark themselves absent here.")
    payload = request.get_json(silent=True) if request.is_json else {}
    if not isinstance(payload, dict):
        payload = {}
    f = Fields(payload)
    f.text("reason", 200)
    errors = f.errors

    for_date = None
    try:
        for_date = date.fromisoformat(str(payload.get("for_date")))
    except (TypeError, ValueError):
        errors["for_date"] = "Give a date as YYYY-MM-DD"
    if for_date is not None and for_date <= today_local():
        errors["for_date"] = "Let them know at least a day ahead"
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    exists = (AbsenceRequest.query.filter_by(user_code=g.user.code, for_date=for_date)
              .filter(AbsenceRequest.status != "rejected").first())
    if exists is not None:
        return jsonify(error="You've already let them know about that day."), 409

    row = AbsenceRequest(user_code=g.user.code, for_date=for_date, reason=f.data.get("reason", ""))
    db.session.add(row)
    db.session.commit()
    return jsonify(absence=row.to_dict()), 201


def _decide_absence(record_id, status):
    if not _can_see_absences(g.user):
        abort(403, "Only the admin or a project manager can act on this.")
    row = db.session.get(AbsenceRequest, record_id)
    if row is None:
        abort(404)
    if row.status != "pending":
        abort(409, "This one has already been dealt with.")
    row.status = status
    row.decided_by_code = g.user.code
    row.decided_at = utcnow()
    db.session.commit()
    return jsonify(absence=row.to_dict())


@bp.post("/api/attendance/absences/<int:record_id>/approve")
def approve_absence(record_id):
    return _decide_absence(record_id, "approved")


@bp.post("/api/attendance/absences/<int:record_id>/reject")
def reject_absence(record_id):
    return _decide_absence(record_id, "rejected")

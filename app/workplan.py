"""Work plan and announcements (kohal, 2026-10-19: "Next day work scheduling by project manager or by
accountant or admin... This allotment should approved by Admin... alert to each user home screen"; later
the same day: "rename work plan to work plan and announcements. both should be a subtabs"): two subtabs on
one page, same shape as Inventory's own Materials/Material requests split -

  - Work plan: a project manager or the accountant drafts a day's work - against a project for a field
    worker ('field'), or a location for office staff ('office') - and only the admin specifically can
    approve it (never Company Director or anyone else who stands in for "admin" elsewhere in this app, see
    auth.can_approve_work_assignment). The admin's own entries are approved immediately, same self-approval
    shortcut as Attendance's check-in.
  - Announcements: the admin sends a message to a chosen set of employees, no approval step (it's purely
    informational) - see auth.can_send_announcement.

This page (gated by the workplan module, see check_module below) is only for drafting/sending and
approving - the assigned/addressed person's own side (the Work plan alert on their Me hub, the announcement
popup on every page) lives in app/me.py and base.html instead, since they usually have no reason to ever
open this module themselves, and app/me.py's routes for it are deliberately *not* behind check_module -
whoever's on the receiving end might not have Workplan module access at all."""

from datetime import date, timedelta

from flask import Blueprint, abort, g, jsonify, render_template, request

from .auth import can_approve_work_assignment, can_draft_work_plan, can_send_announcement, visible_projects
from .extensions import db
from .models import Announcement, AnnouncementRecipient, Project, WorkAssignment, Worker, utcnow
from .modules import check_module
from .validation import Fields, api_errors

bp = Blueprint("workplan", __name__)
api_errors(bp)

KINDS = ("field", "office")
ANNOUNCEMENT_MESSAGE_MAX = 500


@bp.before_request
def _workplan_module():
    check_module("workplan")


@bp.get("/workplan")
def page():
    return render_template("workplan.html", page_title="Work plan and announcements")


def _project_or_404(project_id):
    project = visible_projects().filter(Project.id == project_id).first()
    if project is None:
        abort(422, "Pick a project you can see")
    return project


@bp.get("/api/work-assignments")
def list_for_date():
    """Everyone's work for one day (default tomorrow), plus who/what the form can pick from."""
    raw = request.args.get("date")
    try:
        for_date = date.fromisoformat(raw) if raw else date.today() + timedelta(days=1)
    except ValueError:
        abort(422, "Give the date as YYYY-MM-DD")
    rows = WorkAssignment.query.filter_by(for_date=for_date).order_by(WorkAssignment.created_at).all()
    return jsonify(
        for_date=for_date.isoformat(),
        assignments=[a.to_dict() for a in rows],
        workers=[{"id": w.id, "name": w.name, "has_login": bool(w.user_code)}
                 for w in Worker.query.order_by(Worker.name)],
        projects=[{"id": p.id, "title": p.title, "client_name": p.client.name}
                  for p in visible_projects().filter(Project.status != "completed").order_by(Project.title)],
        can_approve=can_approve_work_assignment(g.user),
    )


def _fields(payload):
    f = Fields(payload)
    f.text("task", 300)
    errors = f.errors

    kind = payload.get("kind")
    if kind not in KINDS:
        errors["kind"] = "Choose field work or office work"

    raw_date = payload.get("for_date")
    try:
        for_date = date.fromisoformat(str(raw_date))
    except (TypeError, ValueError):
        for_date = None
        errors["for_date"] = "Give a date as YYYY-MM-DD"
    if for_date is not None and for_date < date.today():
        errors["for_date"] = "Can't schedule a day that's already passed"

    worker = None
    raw_worker = payload.get("worker_id")
    if str(raw_worker).isdigit():
        worker = db.session.get(Worker, int(raw_worker))
    if worker is None:
        errors["worker_id"] = "Pick an employee"

    project = None
    location = ""
    if kind == "field":
        raw_project = payload.get("project_id")
        if str(raw_project).isdigit():
            project = visible_projects().filter(Project.id == int(raw_project)).first()
        if project is None:
            errors["project_id"] = "Pick a project"
    elif kind == "office":
        location = str(payload.get("location") or "").strip()[:120]
        if not location:
            errors["location"] = "Say where they'll be working"

    if not f.data.get("task"):
        errors.setdefault("task", "Say what the work is")

    return {
        "for_date": for_date, "kind": kind, "worker": worker, "project": project,
        "location": location, "task": f.data.get("task", ""),
    }, errors


@bp.get("/api/work-assignments/pending")
def pending():
    """For the Me hub's own pending-approvals section (kohal: "This allotment should approved by Admin") -
    admin only, same as who may actually act on one."""
    if not can_approve_work_assignment(g.user):
        abort(403, "Only the admin can see this.")
    rows = WorkAssignment.query.filter_by(status="pending").order_by(WorkAssignment.created_at).all()
    return jsonify(assignments=[a.to_dict() for a in rows])


@bp.post("/api/work-assignments")
def create():
    if not can_draft_work_plan(g.user):
        abort(403, "Only a project manager, the accountant, or the admin can schedule work.")
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    data, errors = _fields(payload)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    approved = can_approve_work_assignment(g.user)
    row = WorkAssignment(
        for_date=data["for_date"], kind=data["kind"], worker=data["worker"], project=data["project"],
        location=data["location"], task=data["task"], created_by_code=g.user.code,
        status="approved" if approved else "pending",
        approved_by_code=g.user.code if approved else None,
        approved_at=utcnow() if approved else None,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(assignment=row.to_dict()), 201


@bp.patch("/api/work-assignments/<int:assignment_id>")
def update(assignment_id):
    """Fix a mistake on an already-drafted entry - same who-may rule as deleting one (kohal, 2026-10-19:
    "give option to update work plan"): the admin any time, or whoever drafted it while it's still pending.
    Doesn't touch status/approval either way - the admin editing an already-approved one is trusted to get
    it right without re-approving it, and an edit while still pending just waits on the same approval it
    already was."""
    row = db.session.get(WorkAssignment, assignment_id)
    if row is None:
        abort(404)
    if not (g.user.is_admin or (row.status == "pending" and row.created_by_code == g.user.code)):
        abort(403, "Only the admin, or whoever drafted this while it's still pending, can change it.")
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    data, errors = _fields(payload)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    row.for_date = data["for_date"]
    row.kind = data["kind"]
    row.worker = data["worker"]
    row.project = data["project"]
    row.location = data["location"]
    row.task = data["task"]
    db.session.commit()
    return jsonify(assignment=row.to_dict())


@bp.delete("/api/work-assignments/<int:assignment_id>")
def delete(assignment_id):
    """The admin any time, or whoever drafted it while it's still pending - once approved, deleting it
    would pull the rug out from under an alert someone's already seen."""
    row = db.session.get(WorkAssignment, assignment_id)
    if row is None:
        abort(404)
    if not (g.user.is_admin or (row.status == "pending" and row.created_by_code == g.user.code)):
        abort(403, "Only the admin, or whoever drafted this while it's still pending, can remove it.")
    db.session.delete(row)
    db.session.commit()
    return "", 204


def _decide(assignment_id, status):
    if not can_approve_work_assignment(g.user):
        abort(403, "Only the admin can approve or reject this.")
    row = db.session.get(WorkAssignment, assignment_id)
    if row is None:
        abort(404)
    if row.status != "pending":
        abort(409, "This one has already been dealt with.")
    row.status = status
    row.approved_by_code = g.user.code
    row.approved_at = utcnow()
    db.session.commit()
    return jsonify(assignment=row.to_dict())


@bp.post("/api/work-assignments/<int:assignment_id>/approve")
def approve(assignment_id):
    return _decide(assignment_id, "approved")


@bp.post("/api/work-assignments/<int:assignment_id>/reject")
def reject(assignment_id):
    return _decide(assignment_id, "rejected")


# ---------- announcements (kohal, 2026-10-19) - admin side; the recipient's own side (the popup, dismiss)
# is in app/me.py instead, deliberately not behind this blueprint's check_module("workplan") gate - an
# announcement can go to anyone with a login, whether or not they have Workplan access themselves. ----------

@bp.get("/api/announcements")
def list_announcements():
    """Every announcement ever sent, newest first, with how many have seen it - admin only, same as who
    may send one."""
    if not can_send_announcement(g.user):
        abort(403, "Only the admin can see this.")
    rows = Announcement.query.order_by(Announcement.created_at.desc()).limit(100).all()
    return jsonify(
        announcements=[a.to_dict() for a in rows],
        workers=[{"id": w.id, "name": w.name, "has_login": bool(w.user_code)} for w in Worker.query.order_by(Worker.name)],
    )


@bp.post("/api/announcements")
def send_announcement():
    if not can_send_announcement(g.user):
        abort(403, "Only the admin can send an announcement.")
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    f = Fields(payload)
    f.text("message", ANNOUNCEMENT_MESSAGE_MAX, required=True, label="a message")
    errors = f.errors

    raw_ids = payload.get("worker_ids")
    worker_ids = [int(w) for w in raw_ids if str(w).isdigit()] if isinstance(raw_ids, list) else []
    workers = Worker.query.filter(Worker.id.in_(worker_ids)).all() if worker_ids else []
    # Only who actually has a login ever gets a row to see this on (kohal: "pop up as soon as they open the
    # app") - someone tracked only via WhatsApp has no app to open.
    recipients = [w for w in workers if w.user_code]
    if not worker_ids:
        errors.setdefault("worker_ids", "Choose at least one employee")
    elif not recipients:
        errors["worker_ids"] = "None of the chosen employees have a login to see this"
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    announcement = Announcement(message=f.data["message"], created_by_code=g.user.code)
    db.session.add(announcement)
    db.session.flush()
    for w in recipients:
        db.session.add(AnnouncementRecipient(announcement_id=announcement.id, user_code=w.user_code))
    db.session.commit()
    return jsonify(announcement=announcement.to_dict()), 201

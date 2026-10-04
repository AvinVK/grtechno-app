"""The Me hub (/me): the phone's home for everything that isn't the Leads list - who you are, today's
check-in, a tile per service you can open, the admin's Manage links, and Sign out. It replaces the side
menu on phones; on wider screens the menu stays and /me is just another page. The bottom tabs come from
base.html, like on every other page."""

from datetime import timedelta

from flask import Blueprint, abort, g, jsonify, render_template, request

from . import categories
from .auth import visible_clients, visible_leads, visible_projects
from .constants import OPEN_STAGES
from .extensions import db
from .models import Attendance, Client, Lead, LeadSurvey, Project, SiteCategory, SiteCategoryRequest
from .modules import modules_for
from .timeutil import today_local

bp = Blueprint("me", __name__)


def _summaries(keys) -> dict:
    """A one-line figure for each service tile - only the ones a single count query can answer. Services
    with nothing cheap to say about them get no line, just their name."""
    out = {}
    if "leads" in keys:
        n = visible_leads().filter(Lead.stage.in_(OPEN_STAGES)).count()
        out["leads"] = f"{n} open"
    if "attendance" in keys:
        today = today_local()
        if g.user.is_admin:                          # the admin doesn't check in; show the team instead
            n = Attendance.query.filter(Attendance.work_date == today).count()
            out["attendance"] = f"{n} checked in today"
        else:
            monday = today - timedelta(days=today.weekday())
            n = Attendance.query.filter(Attendance.user_code == g.user.code, Attendance.work_date >= monday).count()
            out["attendance"] = f"{n} day{'' if n == 1 else 's'} this week"
    if "clients" in keys:
        n = visible_clients().count()
        out["clients"] = f"{n} client{'' if n == 1 else 's'}"
    if "projects" in keys:
        n = visible_projects().filter(Project.status == "running").count()
        out["projects"] = f"{n} running"
    return out


@bp.get("/me")
def page():
    keys = {m.key for m in modules_for(g.user)}
    return render_template("me.html", summaries=_summaries(keys),
                           has_attendance="attendance" in keys and not g.user.is_admin)   # no check-in card for the admin


@bp.get("/api/me")
def profile():
    u = g.user
    return jsonify(name=u.name, userid=u.userid, designation=u.role.name if u.role else None, phone=u.phone or "")


@bp.patch("/api/me")
def update_profile():
    """The only thing a signed-in person can change about themselves here: their own contact number."""
    data = request.get_json(silent=True) or {}
    if "phone" not in data:
        return jsonify(error="Nothing to update."), 400
    phone = (data["phone"] or "").strip()
    if len(phone) > 40:
        return jsonify(error="Phone number is too long.", fields={"phone": "Too long"}), 400
    g.user.phone = phone
    db.session.commit()
    return jsonify(phone=g.user.phone)


def _admin_only():
    if not g.user.is_admin:
        abort(403, "Only the admin can approve site categories.")


@bp.get("/api/site-categories/requests")
def pending_categories():
    _admin_only()
    waiting = SiteCategoryRequest.query.filter_by(status="pending").order_by(SiteCategoryRequest.created_at).all()
    return jsonify(
        requests=[{
            "id": r.id, "name": r.name,
            "requested_by": r.requested_by.name if r.requested_by else None,
            "uses": LeadSurvey.query.filter_by(site_category=r.name).count() + Client.query.filter_by(site_category=r.name).count(),
        } for r in waiting],
        categories=SiteCategory.active_names(),
    )


@bp.post("/api/site-categories/requests/<int:request_id>/approve")
def approve_category(request_id):
    _admin_only()
    req = db.get_or_404(SiteCategoryRequest, request_id)
    if req.status != "pending":
        abort(409, "This one has already been dealt with.")
    categories.approve(req)
    db.session.commit()
    return jsonify(ok=True)


@bp.post("/api/site-categories/requests/<int:request_id>/redirect")
def redirect_category(request_id):
    _admin_only()
    req = db.get_or_404(SiteCategoryRequest, request_id)
    if req.status != "pending":
        abort(409, "This one has already been dealt with.")
    target = (request.get_json(silent=True) or {}).get("target")
    if target not in SiteCategory.active_names():
        abort(422, "Choose an existing category.")
    categories.redirect(req, target)
    db.session.commit()
    return jsonify(ok=True)

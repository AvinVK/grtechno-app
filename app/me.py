"""The Me hub (/me): the phone's home for everything that isn't the Leads list - who you are, a tile per
service you can open, the admin's Manage links, and Sign out. Today's check-in itself lives on the
Attendance tab now, not duplicated here (kohal, 2026-10-16) - this just shows the week's count on its tile,
like every other service. Replaces the side menu on phones; on wider screens the menu stays and /me is just
another page. The bottom tabs come from base.html, like on every other page."""

from datetime import timedelta

from flask import Blueprint, abort, g, jsonify, render_template, request

from . import categories
from .auth import (
    can_approve_stock_in,
    can_approve_work_assignment,
    can_manage_fooding,
    visible_clients,
    visible_leads,
    visible_projects,
)
from .constants import COMMISSION_ROLE_KEY, OPEN_STAGES
from .extensions import db
from .fooding import _fooding_eligible_query as fooding_eligible_workers, account_for
from .models import (
    Announcement,
    AnnouncementRecipient,
    Attendance,
    Client,
    Lead,
    LeadSurvey,
    MaterialMovement,
    Project,
    SiteCategory,
    SiteCategoryRequest,
    WorkAssignment,
    Worker,
    utcnow,
)
from .modules import has_module, modules_for
from .timeutil import today_local

bp = Blueprint("me", __name__)


def _summaries(keys) -> dict:
    """A one-line figure for each service tile - only the ones a single count query can answer. Services
    with nothing cheap to say about them get no line, just their name."""
    out = {}
    if "leads" in keys:
        today = today_local()
        open_leads = visible_leads().filter(Lead.stage.in_(OPEN_STAGES))
        n = open_leads.count()
        overdue = open_leads.filter(Lead.follow_up_date < today).count()
        out["leads"] = f"{n} open · {overdue} overdue" if overdue else f"{n} open"
    if "attendance" in keys:
        today = today_local()
        if g.user.is_admin:                          # the admin doesn't check in; show the team instead
            n = Attendance.query.filter(Attendance.work_date == today).count()
            out["attendance"] = f"{n} checked in today"
        else:
            monday = today - timedelta(days=today.weekday())
            # Only an approved day counts here (see Attendance.status) - a pending one isn't a verified
            # day's work yet.
            n = Attendance.query.filter(Attendance.user_code == g.user.code, Attendance.work_date >= monday,
                                         Attendance.status == "approved").count()
            out["attendance"] = f"{n} day{'' if n == 1 else 's'} this week"
    if "clients" in keys:
        n = visible_clients().count()
        out["clients"] = f"{n} client{'' if n == 1 else 's'}"
    if "projects" in keys:
        n = visible_projects().filter(Project.status == "running").count()
        out["projects"] = f"{n} running"
    return out


def _extra_tiles():
    """Wages/Fooding (kohal, 2026-10-18) aren't modules - who gets which of these tiles, in the same
    Services grid as the real ones (kohal: "i wasnt fooding blobk here in missing space"), depends on
    something other than a role:
    - the admin or accountant (auth.can_manage_fooding) gets a Fooding tile - a real page, /fooding (kohal:
      "dude, fooding should open its own page!" - it used to only jump to a block further down this one).
    - someone fooding_eligible (Worker.fooding_eligible - every daily-wage worker automatically, or a
      salaried/contractor one who's opted in, kohal: "now there are salaried employees which can be on
      200rs fooding thing") gets their own Fooding tile, a real page (see app/fooding.py).
    - a daily-wage worker specifically (not just anyone fooding_eligible) also gets a Wages tile (see
      app/wages.py) - a salaried person already has their pay on file elsewhere, so there's nothing for
      that placeholder to show them.
    - the Project manager Chandrapur role gets a Commission tile (kohal, 2026-10-18: "this guy has to see
      his comissions, how does he check that?" - previously only visible to an admin, through Employee
      management's own popup), a real page (see app/commissions.py)."""
    from .models import settings_for_client

    tiles = []
    if can_manage_fooding(g.user):
        n = fooding_eligible_workers().count()
        tiles.append({"href": "/fooding", "icon": "fooding", "name": "Fooding",
                       "sum": f"{n} on fooding" if n else None})
        return tiles
    worker = Worker.query.filter_by(user_code=g.user.code).first()
    if worker and worker.employment_type == "daily_wages":
        tiles.append({"href": "/wages", "icon": "wages", "name": "Wages", "sum": None})
    if worker and worker.fooding_eligible:
        account = account_for(worker)
        db.session.commit()       # account_for settles it - persist that, same as the API routes do
        remaining = account.remaining if account else None
        cur = settings_for_client()["currency"]
        tiles.append({"href": "/fooding", "icon": "fooding", "name": "Fooding",
                       "sum": f"{cur}{remaining:.0f} left" if remaining is not None else None})
    if worker and worker.role_key == COMMISSION_ROLE_KEY:
        cur = settings_for_client()["currency"]
        tiles.append({"href": "/commissions", "icon": "commission", "name": "Commission",
                       "sum": f"{cur}{worker.commission_total:.0f} earned" if worker.commission_total else None})
    return tiles


@bp.get("/me")
def page():
    keys = {m.key for m in modules_for(g.user)}
    return render_template("me.html", summaries=_summaries(keys), extra_tiles=_extra_tiles(),
                           # Users & roles / Employee management aren't in_nav (see modules_for), so they
                           # aren't in keys above - checked separately for the Me hub's own Manage section.
                           can_see_users=has_module(g.user, "users"),
                           can_see_workforce=has_module(g.user, "workforce"))


@bp.get("/api/me/work-assignment")
def my_work_assignment():
    """The signed-in worker's own next piece of scheduled work, once approved (kohal, 2026-10-19: "alert to
    each user home screen") - the soonest upcoming one (today or later), or null once there's nothing left
    to show. Nothing to do with the workplan module - whoever's assigned usually has no access to it at
    all, this is just "what's waiting for me" the same way material/attendance approvals are."""
    worker = Worker.query.filter_by(user_code=g.user.code).first()
    if worker is None:
        return jsonify(assignment=None)
    row = (WorkAssignment.query.filter_by(worker_id=worker.id, status="approved")
           .filter(WorkAssignment.for_date >= today_local())
           .order_by(WorkAssignment.for_date).first())
    return jsonify(assignment=row.to_dict() if row else None)


@bp.get("/api/me/announcements")
def my_announcements():
    """Undismissed announcements waiting for the signed-in person (kohal, 2026-10-19: "the selected users
    should get a pop up as soon as they open the app") - oldest first, so if more than one is waiting they
    see them in the order they were sent. Nothing to do with the workplan module, same reasoning as
    my_work_assignment above - checked on every page (see base.html), not just here."""
    rows = (AnnouncementRecipient.query.join(Announcement)
            .filter(AnnouncementRecipient.user_code == g.user.code, AnnouncementRecipient.dismissed_at.is_(None))
            .order_by(Announcement.created_at).all())
    return jsonify(announcements=[{**r.announcement.to_dict(), "recipient_id": r.id} for r in rows])


@bp.post("/api/me/announcements/<int:recipient_id>/dismiss")
def dismiss_announcement(recipient_id):
    """The "cut" button on the popup (kohal, 2026-10-19: "a cut option to remove the popup") - only the
    person it was actually sent to can dismiss their own copy."""
    row = db.session.get(AnnouncementRecipient, recipient_id)
    if row is None or row.user_code != g.user.code:
        return jsonify(error="Not found"), 404
    row.dismissed_at = utcnow()
    db.session.commit()
    return "", 204


@bp.get("/api/me/material-approvals")
def material_approvals():
    """Pending stock-ins the signed-in person specifically can approve right now (kohal, 2026-10-16: "i want
    to see the requests in me tab"), same eligibility as Inventory's own approve route (auth.
    can_approve_stock_in). An issue request moved to its own tab inside Inventory (kohal, 2026-10-17) rather
    than being approved from here or from the project - anyone with Inventory access already sees it there,
    so it's dropped from this list rather than shown twice with no way to act on it from here."""
    pending = MaterialMovement.query.filter_by(status="pending", kind="in").order_by(MaterialMovement.created_at).all()
    rows = []
    for mv in pending:
        if not can_approve_stock_in(g.user):
            continue
        rows.append({
            "id": mv.id, "kind": mv.kind, "material_id": mv.material_id,
            "material_name": mv.material.name, "material_code": mv.material.code,
            "quantity": float(mv.quantity), "unit": mv.material.unit,
            "project_id": mv.project_id, "project_title": mv.project.title if mv.project else None,
            "project_code": mv.project.code if mv.project else None,
            "requested_by": mv.created_by.name if mv.created_by else None,
            "note": mv.note,
        })
    return jsonify(approvals=rows)


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

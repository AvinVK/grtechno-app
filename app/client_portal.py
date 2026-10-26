"""The client portal (kohal, 2026-10-22: "now i wanna create a new acccess for clients. clients should be
able to login... client should only be able to see the projects they belong to... there should be a new
subtab in projects called progress. this should be visible only to admin and client role... client should
be able to see only this subtab of his projects"): a customer's own, read-only view of their project(s) -
a cut-down list (their own Client's projects only, via auth.visible_projects' own "client" branch) and,
per project, the Overview/Payment/More details/Progress tabs (kohal, 2026-10-23: everything except
materials, expenses and attendance, view only) - nothing else in this app at all. Deliberately not the Module system (app/modules.py) - a client role has no ROLE_MODULES row and
never will, since nothing here is a Services tile; this blueprint is gated on role_key == "client" alone,
its own separate surface from app/projects.py's admin-facing one.

Progress itself (kohal, 2026-10-22: "stages of project, work pics at each phase") is the fixed installation
checklist from constants.PROJECT_STAGES/Project.stage_rows, read-only here - the admin's own matching
"Progress" subtab lives in app/projects.py/app/static/js/projects.js instead, inside the normal project
detail page, where it's editable; this blueprint is the client-only mirror of just that one tab, not a copy
of the whole page."""

from flask import Blueprint, abort, g, jsonify, render_template, request, url_for

from .auth import visible_projects
from .constants import PAUSE_REASONS, PROJECT_ATTACHMENT_TYPES, PROJECT_DOCUMENT_TYPES
from .models import Project, settings_for_client
from .timeutil import to_local

bp = Blueprint("client_portal", __name__)

# What a client sees on top of the summary, taken from Project.to_dict(detail=True) - money, dates, site,
# terms, payment schedule and the closing documents. Nothing internal (manager_code, lead_id, ...).
_DETAIL_FIELDS = (
    "estimated_amount", "discount_amount", "final_amount", "net_amount", "paid_amount", "manager_name",
    "site_address", "site_city", "site_district", "site_state", "site_pincode",
    "work_order_no", "work_order_date", "start_date", "completion_days",
    "payment_terms", "special_terms", "payments", "documents",
)


@bp.before_request
def _client_only():
    if request.endpoint == "client_portal.welcome":
        return None       # the landing page is public - see auth.PUBLIC_ENDPOINTS
    if g.user.role_key != "client":
        abort(403, "This is a client's own sign-in.")


def _own_project_or_404(project_id):
    project = visible_projects().filter(Project.id == project_id).first()
    if project is None:
        abort(404)
    return project


def _project_summary(project) -> dict:
    return {
        "id": project.id, "code": project.code, "title": project.title,
        "site_name": project.site_name, "status": project.status,
    }


# kohal, 2026-10-26: "whenever i share the login details to client, first they should land on a landing page of
# the business. i wanna advertise my business there" - the first screen after a client signs in (auth._landing_url),
# built from the business's own website page; its one way onward is the "My projects" button.
@bp.get("/welcome")
def welcome():
    # Signed in as a client: straight to their projects. Anyone else: the client sign-in, which then comes back
    # to their projects.
    if g.user is not None and g.user.role_key == "client":
        projects_url = url_for("client_portal.my_projects")
    else:
        projects_url = url_for("auth.login", **{"as": "client", "next": url_for("client_portal.my_projects")})
    return render_template("client_landing.html", projects_url=projects_url)


@bp.get("/my-projects")
def my_projects():
    return render_template("client_portal.html")


@bp.get("/api/my-projects")
def list_my_projects():
    projects = visible_projects().order_by(Project.id.desc()).all()
    return jsonify(projects=[_project_summary(p) for p in projects])


@bp.get("/api/my-projects/<int:project_id>")
def my_project_detail(project_id):
    project = _own_project_or_404(project_id)
    # The same fixed checklist the admin's own Progress tab shows (app/projects.py), read-only here - see
    # Project.stage_rows (kohal, 2026-10-22: "stages of project... work pics at each phase"). pause_reasons
    # is just the key -> label lookup for whatever reason is already on a paused stage - a client never
    # picks one themselves.
    #
    # kohal, 2026-10-23: "now client should be able to see everything in project except material, expenses
    # and attendance. only view access" - so the Overview, Payment and More details tabs are mirrored here
    # too, built from Project.to_dict(detail=True). Left out on purpose: materials, expenses (incl. computed
    # wages), the attendance team list, and who brought the lead in - none of those are the client's to see.
    detail = project.to_dict(detail=True)
    client = project.client
    return jsonify(
        project={**_project_summary(project), **{k: detail[k] for k in _DETAIL_FIELDS}},
        client={"name": client.name, "contact_name": client.contact_name, "phone": client.phone},
        # The work order (BOQ) and purchase order come first (kohal, 2026-10-26: "show work order (BOQ) and
        # purchase order in progress as well for client view"), then the closing documents.
        document_types=PROJECT_ATTACHMENT_TYPES + PROJECT_DOCUMENT_TYPES,
        attachment_types=PROJECT_ATTACHMENT_TYPES,
        dashboard={
            # Same "Running for" basis as app/projects.py's _detail: the start date if set, else the day it was added.
            "started": (project.start_date or to_local(project.created_at).date()).isoformat(),
            "start_date_set": project.start_date is not None,
            "completed_at": project.completed_at.isoformat() + "Z" if project.completed_at else None,
        },
        stages=project.stage_rows,
        current_stage_key=project.current_stage_key, pause_reasons=PAUSE_REASONS,
        currency=settings_for_client()["currency"],
    )

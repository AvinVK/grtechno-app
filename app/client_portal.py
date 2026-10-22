"""The client portal (kohal, 2026-10-22: "now i wanna create a new acccess for clients. clients should be
able to login... client should only be able to see the projects they belong to... there should be a new
subtab in projects called progress. this should be visible only to admin and client role... client should
be able to see only this subtab of his projects"): a customer's own, read-only view of their project(s) -
a cut-down list (their own Client's projects only, via auth.visible_projects' own "client" branch) and,
per project, the Progress tab alone - no Payment/Materials/Expense/More details, nothing else in this app
at all. Deliberately not the Module system (app/modules.py) - a client role has no ROLE_MODULES row and
never will, since nothing here is a Services tile; this blueprint is gated on role_key == "client" alone,
its own separate surface from app/projects.py's admin-facing one.

Progress itself (kohal, 2026-10-22: "stages of project, work pics at each phase") is the fixed installation
checklist from constants.PROJECT_STAGES/Project.stage_rows, read-only here - the admin's own matching
"Progress" subtab lives in app/projects.py/app/static/js/projects.js instead, inside the normal project
detail page, where it's editable; this blueprint is the client-only mirror of just that one tab, not a copy
of the whole page."""

from flask import Blueprint, abort, g, jsonify, render_template

from .auth import visible_projects
from .models import Project

bp = Blueprint("client_portal", __name__)


@bp.before_request
def _client_only():
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
    # Project.stage_rows (kohal, 2026-10-22: "stages of project... work pics at each phase").
    return jsonify(project=_project_summary(project), stages=project.stage_rows)

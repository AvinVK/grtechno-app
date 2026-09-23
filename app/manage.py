"""All clients and All projects (admin only): the company-wide view under Manage, grouped by area, as
opposed to the ordinary Clients and Projects services which each person sees scoped to their own work.
No API of its own - both pages call the same /api/clients and /api/projects the ordinary pages use, which
already return everything to the admin (sees_all), and just group the result by geography client-side."""

from flask import Blueprint, g, render_template
from werkzeug.exceptions import abort

bp = Blueprint("manage", __name__)


@bp.before_request
def admin_only():
    if not g.user or not g.user.is_admin:
        abort(403, "Only the admin can open this page.")


@bp.get("/all-clients")
def all_clients():
    return render_template("all_clients.html", heading="All clients", heading_href="/all-clients")


@bp.get("/all-projects")
def all_projects():
    return render_template("all_projects.html", heading="All projects", heading_href="/all-projects")

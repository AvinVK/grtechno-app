"""The Me hub (/me): the phone's home for everything that isn't the Leads list - who you are, today's
check-in, a tile per service you can open, the admin's Manage links, and Sign out. It replaces the side
menu on phones; on wider screens the menu stays and /me is just another page."""

from datetime import timedelta

from flask import Blueprint, g, render_template

from .auth import visible_clients, visible_leads, visible_projects
from .constants import OPEN_STAGES
from .models import Attendance, Lead, Project
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
    return render_template("me.html", heading="Me", heading_href="/me", summaries=_summaries(keys),
                           has_attendance="attendance" in keys)

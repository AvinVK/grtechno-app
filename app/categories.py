"""Site categories typed in by people (not on the list yet). A typed one waits as a request until the admin
approves it, or points it at an existing category - only then does it touch the category list."""

from .extensions import db
from .models import Client, LeadSurvey, SiteCategory, SiteCategoryRequest


def note_request(name: str, user_code: str | None) -> None:
    """Remember a typed category the list doesn't have, unless it's already on the list or already waiting."""
    name = (name or "").strip()[:60]
    if not name:
        return
    with db.session.no_autoflush:
        if name in SiteCategory.active_names():
            return
        waiting = SiteCategoryRequest.query.filter_by(name=name, status="pending").first()
        if waiting is None:
            db.session.add(SiteCategoryRequest(name=name, requested_by_code=user_code))


def approve(req: SiteCategoryRequest) -> None:
    if SiteCategory.query.filter_by(name=req.name).first() is None:
        top = db.session.query(db.func.max(SiteCategory.sort_order)).scalar() or 0
        db.session.add(SiteCategory(name=req.name, sort_order=top + 1, is_active=True))
    req.status = "approved"


def redirect(req: SiteCategoryRequest, target: str) -> None:
    """Point the typed name at an existing category: every survey and client using it is changed too."""
    LeadSurvey.query.filter_by(site_category=req.name).update({"site_category": target})
    Client.query.filter_by(site_category=req.name).update({"site_category": target})
    req.status = "redirected"
    req.target = target

"""Commission: a Project manager Chandrapur's own read-only view of what they've earned, project by
project (kohal, 2026-10-18: "now this guy has to see his comissions, how does he check that?" - until now
the only place this showed at all was an admin's own Employee management popup; this is the same figures,
just reachable from the person's own Me hub). See Worker.commission_total/commissions in app/models.py for
where the numbers come from, and app/projects.py's own /expenses routes for how a commission entry is
actually created - from a project's Payment tab, not here. This page never writes anything."""

from flask import Blueprint, abort, g, jsonify, render_template

from .constants import COMMISSION_ROLE_KEY
from .models import Worker, settings_for_client

bp = Blueprint("commissions", __name__)


def own_commission_worker():
    """The Worker row standing in for the signed-in person, if any - see auth.sync_worker_for_user - and
    only if they're actually in the role that earns commission (kohal's access matrix: commission is tied
    to the Project manager Chandrapur role specifically, not every worker with a stray commission entry)."""
    worker = Worker.query.filter_by(user_code=g.user.code).first()
    if worker is None or worker.role_key != COMMISSION_ROLE_KEY:
        abort(403, "Commission is only for the Project manager Chandrapur role.")
    return worker


@bp.get("/commissions")
def page():
    own_commission_worker()
    return render_template("commissions.html")


@bp.get("/api/commissions/me")
def my_commissions():
    worker = own_commission_worker()
    return jsonify(
        commission_total=float(worker.commission_total),
        commissions=[c.to_dict() for c in worker.commissions if c.kind == "commission"],
        currency=settings_for_client()["currency"],
    )

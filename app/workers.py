"""Worker list (admin only): field workers who don't sign in to the app, tracked instead from the WhatsApp
group where they mark their attendance. Read-only for now - the data comes in through a one-off import,
not through this screen."""

from flask import Blueprint, g, jsonify, render_template
from werkzeug.exceptions import HTTPException, abort

from .extensions import db
from .models import Worker

WINDOW_DAYS = 14           # how many days back the one-off WhatsApp import covers; shown next to each count

bp = Blueprint("workers", __name__, url_prefix="/api/workers")
page_bp = Blueprint("workers_page", __name__)             # the /workers page; the JSON API above is under /api/workers


@bp.errorhandler(HTTPException)
def json_error(err):
    return jsonify(error=err.description or err.name), err.code


@bp.before_request
def admin_only():
    if not g.user or not g.user.is_admin:
        abort(403, "Only the admin can do this.")


@page_bp.before_request
def admin_only_page():
    if not g.user or not g.user.is_admin:
        abort(403, "Only the admin can open this page.")


@page_bp.get("/workers")
def page():
    return render_template("workers.html", heading="Manpower list", heading_href="/workers")


def _summary(worker: Worker) -> dict:
    return {**worker.to_dict(), "days_present": len(worker.attendance), "window_days": WINDOW_DAYS}


@bp.get("")
def list_workers():
    workers = Worker.query.order_by(Worker.name).all()
    return jsonify(workers=[_summary(w) for w in workers], window_days=WINDOW_DAYS)


@bp.get("/<int:worker_id>")
def get_worker(worker_id):
    worker = db.session.get(Worker, worker_id)
    if worker is None:
        abort(404)
    return jsonify(worker=worker.to_dict(), attendance=[a.to_dict() for a in worker.attendance], window_days=WINDOW_DAYS)

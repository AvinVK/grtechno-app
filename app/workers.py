"""Manpower list and Staff list (admin only): field workers and office staff who don't sign in to the app,
tracked instead from the WhatsApp group each marks their attendance in. Same table (Worker.category tells
them apart), two separate pages. Read-only for now - the data comes in through a one-off import, not
through this screen."""

from flask import Blueprint, g, jsonify, render_template
from werkzeug.exceptions import HTTPException, abort

from .extensions import db
from .models import Worker

WINDOW_DAYS = 14           # how many days back the one-off WhatsApp import covers; shown next to each count

bp = Blueprint("workers", __name__, url_prefix="/api/workers")            # Manpower's JSON API
page_bp = Blueprint("workers_page", __name__)                             # the /workers page
staff_bp = Blueprint("staff", __name__, url_prefix="/api/staff")          # Staff's JSON API
staff_page_bp = Blueprint("staff_page", __name__)                         # the /staff page


@bp.errorhandler(HTTPException)
@staff_bp.errorhandler(HTTPException)
def json_error(err):
    return jsonify(error=err.description or err.name), err.code


@bp.before_request
@staff_bp.before_request
def admin_only():
    if not g.user or not g.user.is_admin:
        abort(403, "Only the admin can do this.")


@page_bp.before_request
@staff_page_bp.before_request
def admin_only_page():
    if not g.user or not g.user.is_admin:
        abort(403, "Only the admin can open this page.")


@page_bp.get("/workers")
def page():
    return render_template("workers.html", heading="Manpower list", heading_href="/workers")


@staff_page_bp.get("/staff")
def staff_page():
    return render_template("staff.html", heading="Staff list", heading_href="/staff")


def _summary(worker: Worker) -> dict:
    return {**worker.to_dict(), "days_present": len(worker.attendance), "window_days": WINDOW_DAYS}


def _list(category):
    workers = Worker.query.filter_by(category=category).order_by(Worker.name).all()
    return jsonify(workers=[_summary(w) for w in workers], window_days=WINDOW_DAYS)


def _detail(category, worker_id):
    worker = Worker.query.filter_by(id=worker_id, category=category).first()
    if worker is None:
        abort(404)
    return jsonify(worker=worker.to_dict(), attendance=[a.to_dict() for a in worker.attendance], window_days=WINDOW_DAYS)


@bp.get("")
def list_workers():
    return _list("manpower")


@bp.get("/<int:worker_id>")
def get_worker(worker_id):
    return _detail("manpower", worker_id)


@staff_bp.get("")
def list_staff():
    return _list("staff")


@staff_bp.get("/<int:worker_id>")
def get_staff(worker_id):
    return _detail("staff", worker_id)

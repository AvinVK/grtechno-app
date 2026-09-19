from flask import Blueprint, g, jsonify
from sqlalchemy import func
from werkzeug.exceptions import HTTPException, abort

from .api import _payload
from .auth import SETUP_CODE_DAYS, create_user, issue_setup_code
from .extensions import db
from .models import Lead, User, utcnow

bp = Blueprint("users", __name__, url_prefix="/api/users")


@bp.errorhandler(HTTPException)
def json_error(err):
    return jsonify(error=err.description or err.name), err.code


@bp.before_request
def admin_only():
    if not g.user or not g.user.is_admin:
        abort(403, "Only the admin can do this.")


def _dict(user: User, lead_count: int = 0) -> dict:
    pending = user.status == "pending"
    return {
        "code": user.code,
        "userid": user.userid,
        "name": user.name,
        "is_admin": user.is_admin,
        "status": user.status,
        "code_expired": bool(pending and user.setup_code_expires and user.setup_code_expires < utcnow()),
        "leads": lead_count,
    }


def _lead_counts() -> dict:
    rows = db.session.query(Lead.owner_code, func.count(Lead.id)).group_by(Lead.owner_code).all()
    return {code: n for code, n in rows}


@bp.get("")
def list_users():
    counts = _lead_counts()
    users = User.query.order_by(User.is_admin.desc(), User.created_at, User.code).all()
    return jsonify(users=[_dict(u, counts.get(u.code, 0)) for u in users], code_days=SETUP_CODE_DAYS)


@bp.post("")
def add_user():
    name = _payload().get("name")
    if not isinstance(name, str):
        abort(422, "Enter a name.")
    try:
        user, setup_code = create_user(name)
    except ValueError as err:
        return jsonify(error=str(err), fields={"name": str(err)}), 422
    db.session.commit()
    return jsonify(user=_dict(user), setup_code=setup_code, code_days=SETUP_CODE_DAYS), 201


@bp.post("/<code>/reset")
def reset_user(code):
    user = db.get_or_404(User, code)
    if user.is_admin:
        abort(400, "The admin's PIN is reset from the command line: flask --app wsgi reset-pin " + user.userid)
    setup_code = issue_setup_code(user)
    db.session.commit()
    return jsonify(user=_dict(user), setup_code=setup_code, code_days=SETUP_CODE_DAYS)


@bp.post("/<code>/active")
def set_active(code):
    user = db.get_or_404(User, code)
    if user.is_admin:
        abort(400, "The admin account cannot be switched off.")
    active = _payload().get("active")
    if not isinstance(active, bool):
        abort(422, "Say whether the account should be on or off.")
    user.is_active = active
    db.session.commit()
    return jsonify(user=_dict(user))

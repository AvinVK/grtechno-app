"""The services (Leads, and later attendance, manpower, ...) that appear in the sidebar.

They are rows in the `modules` table. A service is a set of pages and API routes; to make it respect
that row (turned off, or admin only) call check_module("key") from its routes, or put
@module_required("key") on them, or call check_module in a blueprint's before_request."""

from functools import wraps

from flask import Blueprint, abort, g, jsonify

from .extensions import db
from .models import Module, RoleModule

bp = Blueprint("modules", __name__, url_prefix="/api/modules")


def _allowed_keys(user) -> set:
    return {r.module_key for r in RoleModule.query.filter_by(role_key=user.role_key)}


def modules_for(user) -> list:
    """Active services this person may use, in menu order. The admin can use all of them; everyone else
    can use the services their role is given in the role_modules table (and never admin-only ones)."""
    rows = Module.query.filter_by(is_active=True).order_by(Module.sort_order, Module.name).all()
    if user.is_admin:
        return rows
    allowed = _allowed_keys(user)
    return [m for m in rows if m.key in allowed and not m.admin_only]


def check_module(key: str) -> Module:
    """Stop the request unless the signed-in person may use this service."""
    module = db.session.get(Module, key)
    if module is None or not module.is_active:
        abort(404)
    if not g.user.is_admin:
        if module.admin_only:
            abort(403, "Only the admin can use this.")
        if key not in _allowed_keys(g.user):
            abort(403, "Your role cannot use this.")
    g.module_key = key
    return module


def module_required(key: str):
    def decorate(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            check_module(key)
            return view(*args, **kwargs)
        return wrapper
    return decorate


@bp.get("")
def list_modules():
    return jsonify(modules=[
        {"key": m.key, "name": m.name, "icon": m.icon, "path": m.path} for m in modules_for(g.user)
    ])

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
    """Active services this person may use, in menu order - just the ones shown as a tile (Module.in_nav);
    Users & roles and Employee management are reached from their own "Manage" section instead (see
    _me_links.html) even though they're gated the exact same way (check_module). The admin can use all of
    them; everyone else can use the services their role is given in the role_modules table (and never
    admin-only ones)."""
    rows = Module.query.filter_by(is_active=True, in_nav=True).order_by(Module.sort_order, Module.name).all()
    if user.is_admin:
        return rows
    allowed = _allowed_keys(user)
    return [m for m in rows if m.key in allowed and not m.admin_only]


def check_module(key: str, write: bool = False) -> Module:
    """Stop the request unless the signed-in person may use this service - and, if write is True, unless
    they may also change things there, not just look (RoleModule.write_access; always True for the
    admin). Used for in_nav tiles and for Users & roles / Employee management alike."""
    module = db.session.get(Module, key)
    if module is None or not module.is_active:
        abort(404)
    if not g.user.is_admin:
        if module.admin_only:
            abort(403, "Only the admin can use this.")
        row = RoleModule.query.filter_by(role_key=g.user.role_key, module_key=key).first()
        if row is None:
            abort(403, "Your role cannot use this.")
        if write and not row.write_access:
            abort(403, "Your role can only view this, not change it.")
    g.module_key = key
    return module


def has_module(user, key: str) -> bool:
    """Whether this person may open this service at all (read access) - for deciding what to show (e.g.
    the Me hub's Manage links for Users & roles / Employee management, which aren't in_nav so modules_for()
    leaves them out), not for enforcing it; the route itself still calls check_module."""
    if user.is_admin:
        return True
    module = db.session.get(Module, key)
    if module is None or not module.is_active or module.admin_only:
        return False
    return RoleModule.query.filter_by(role_key=user.role_key, module_key=key).first() is not None


def can_write(user, key: str) -> bool:
    """Same write check as check_module(write=True), without aborting - for deciding whether to show an
    edit control at all, e.g. in a template. The route itself must still call check_module(key, write=True)
    before actually making the change; hiding a button is not access control on its own."""
    if user.is_admin:
        return True
    row = RoleModule.query.filter_by(role_key=user.role_key, module_key=key).first()
    return bool(row and row.write_access)


def module_required(key: str, write: bool = False):
    def decorate(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            check_module(key, write=write)
            return view(*args, **kwargs)
        return wrapper
    return decorate


@bp.get("")
def list_modules():
    return jsonify(modules=[
        {"key": m.key, "name": m.name, "icon": m.icon, "path": m.path} for m in modules_for(g.user)
    ])

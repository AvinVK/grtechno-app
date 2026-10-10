"""Roles (admin only, JSON only, no page of its own): the one piece of Users & roles that both Add user
and Add employee need to reach - adding a role on the fly when the one they need isn't in the list yet.
A role is just a shared label (plus whether it sees every client/project): it carries no module access of
its own until the admin sets that up directly in the database, the same way the built-in roles got theirs.

Employees (Worker, see models.py/workers.py) and users (User, see models.py/users.py) stay two separate
tables - adding an employee here never creates a user, and adding a role here never makes an employee show
up on the Users & roles page. role_key is only a label the two happen to share the same list for."""

import re

from flask import Blueprint, g, jsonify, request
from werkzeug.exceptions import HTTPException, abort

from .extensions import db
from .models import Role

bp = Blueprint("roles", __name__, url_prefix="/api/roles")


@bp.errorhandler(HTTPException)
def json_error(err):
    return jsonify(error=err.description or err.name), err.code


@bp.before_request
def admin_only():
    if not g.user or not g.user.is_admin:
        abort(403, "Only the admin can do this.")


def _payload():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    return payload


def _slug(name: str) -> str:
    """A primary-key-safe key from a role name: lowercase, non-letters/digits become underscores, no
    leading/trailing ones, at most 30 characters (the column's length)."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return (slug or "role")[:30]


@bp.post("")
def add_role():
    """Add a role, same as the ones seeded at setup - just with no module access yet (see the module
    docstring). name must be new; the key is derived from it and de-duplicated if that slug is taken."""
    name = str(_payload().get("name") or "").strip()[:60]
    if not name:
        return jsonify(error="Check the highlighted fields", fields={"name": "Enter a role name"}), 422
    if Role.query.filter(db.func.lower(Role.name) == name.lower()).first():
        return jsonify(error="Check the highlighted fields", fields={"name": "That role already exists"}), 422
    base = _slug(name)
    key, suffix = base, 2
    while db.session.get(Role, key) is not None:
        key = f"{base[:27]}_{suffix}"
        suffix += 1
    role = Role(key=key, name=name, sees_all=False)
    db.session.add(role)
    db.session.commit()
    return jsonify(role={"key": role.key, "name": role.name}), 201

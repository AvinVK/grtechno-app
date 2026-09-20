"""Clients (the Client Management service): the customers work is done for."""

import re

from flask import Blueprint, g, jsonify, render_template, request
from werkzeug.exceptions import abort

from .auth import visible_clients, visible_projects
from .extensions import db
from .models import Client, Project, settings_for_client
from .modules import check_module
from .validation import Fields, api_errors

bp = Blueprint("clients", __name__)
api_errors(bp)

PINCODE_RE = re.compile(r"[1-9][0-9]{5}")


@bp.before_request
def _clients_service():
    check_module("clients")


def _client_or_404(client_id: int) -> Client:
    client = visible_clients().filter(Client.id == client_id).first()
    if client is None:
        abort(404)
    return client


def _fields(payload, creating):
    f = Fields(payload)
    f.text("name", 160, required=True, label="the client's name")
    f.text("contact_name", 120)
    f.text("phone", 40)
    f.text("email", 160)
    f.text("site_category", 60)
    f.text("pincode", 6)
    f.text("state", 80)
    f.text("district", 80)
    f.text("city", 120)
    f.text("address", 400)
    f.text("notes", 5000)
    if creating and "name" not in payload:
        f.errors["name"] = "Enter the client's name"
    if f.data.get("pincode") and not PINCODE_RE.fullmatch(f.data["pincode"]):
        f.errors["pincode"] = "Enter a 6-digit pincode"
    return f


def _payload():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    return payload


def _project_rows(client):
    rows = visible_projects().filter(Project.client_id == client.id).order_by(Project.id.desc()).all()
    return [{"id": p.id, "code": p.code, "title": p.title, "status": p.status} for p in rows]


@bp.get("/clients")
def page():
    return render_template("clients.html")


@bp.get("/api/clients")
def list_clients():
    clients = visible_clients().order_by(Client.name).all()
    return jsonify(clients=[c.to_dict() for c in clients], site_categories=settings_for_client()["site_categories"])


@bp.get("/api/clients/<int:client_id>")
def get_client(client_id):
    client = _client_or_404(client_id)
    return jsonify(client=client.to_dict(), projects=_project_rows(client), site_categories=settings_for_client()["site_categories"])


@bp.post("/api/clients")
def create_client():
    f = _fields(_payload(), creating=True)
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    client = Client(owner_code=g.user.code, **f.data)
    db.session.add(client)
    db.session.commit()
    return jsonify(client=client.to_dict(), projects=[]), 201


@bp.patch("/api/clients/<int:client_id>")
def update_client(client_id):
    client = _client_or_404(client_id)
    f = _fields(_payload(), creating=False)
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    for key, value in f.data.items():
        setattr(client, key, value)
    db.session.commit()
    return jsonify(client=client.to_dict(), projects=_project_rows(client))

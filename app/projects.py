"""Projects (the Project Management service): work orders, amounts, terms and the payment schedule.
A project normally starts from a won lead (create_project_from_lead) and is then completed by the project
manager or the admin."""

import re
from decimal import Decimal

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy import func
from werkzeug.exceptions import abort

from .auth import visible_projects
from .extensions import db
from .models import Activity, Client, Project, ProjectPayment, User, settings_for_client
from .modules import check_module
from .reference_data import PROJECT_STATUSES
from .validation import Fields, api_errors, parse_money

bp = Blueprint("projects", __name__)
api_errors(bp)

PINCODE_RE = re.compile(r"[1-9][0-9]{5}")


class ProjectError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.message, self.status = message, status


@bp.before_request
def _projects_service():
    check_module("projects")


def create_project_from_lead(lead, user):
    """Turn a won lead into a client (reusing one with the same name) and a project. Returns (project, reused)."""
    if lead.stage != "Won":
        raise ProjectError("Only a won lead can become a project.")
    if lead.project is not None:
        raise ProjectError("This lead already has a project.", 409)

    name = lead.company or lead.contact_name
    client = Client.query.filter(func.lower(Client.name) == name.lower()).first()
    reused = client is not None
    owner = lead.owner_code or user.code
    if client is None:
        client = Client(
            name=name, contact_name=lead.contact_name if lead.company else "", phone=lead.phone, email=lead.email,
            site_category=lead.site_category, pincode=lead.site_pincode, state=lead.site_state,
            district=lead.site_district, city=lead.site_city, address=lead.site_address, owner_code=owner,
        )
        db.session.add(client)

    project = Project(
        client=client, lead=lead, title=f"{name} - {lead.service}" if lead.service else name,
        work_category=lead.service, estimated_amount=lead.est_value, owner_code=owner,
        site_pincode=lead.site_pincode, site_state=lead.site_state, site_district=lead.site_district,
        site_city=lead.site_city, site_address=lead.site_address,
    )
    db.session.add(project)
    db.session.flush()
    lead.activities.insert(0, Activity(kind="project", text=f"Project {project.code} created"))
    return project, reused


def _project_or_404(project_id: int) -> Project:
    project = db.get_or_404(Project, project_id)
    if not g.user.sees_all and g.user.code not in (project.owner_code, project.manager_code):
        abort(404)
    return project


def _payments(raw, errors):
    """Check a payment schedule from the request. Returns a list of dicts, or None if it has problems."""
    if not isinstance(raw, list) or len(raw) > 30:
        errors["payments"] = "The payment schedule should be a list of up to 30 steps"
        return None
    rows = []
    for i, item in enumerate(raw, start=1):
        f = Fields(item if isinstance(item, dict) else {})
        f.text("label", 120, required=True, label="a name for each payment step")
        f.date("due_date")
        problems = dict(f.errors)
        amount = parse_money(item.get("amount", 0) if isinstance(item, dict) else 0, problems, "amount")
        if problems:
            errors["payments"] = f"Payment step {i}: {next(iter(problems.values()))}"
            return None
        rows.append({"label": f.data["label"], "amount": amount, "due_date": f.data.get("due_date")})
    return rows


@bp.get("/projects")
def page():
    return render_template("projects.html")


@bp.get("/api/projects")
def list_projects():
    projects = visible_projects().order_by(Project.id.desc()).all()
    return jsonify(
        projects=[p.to_dict() for p in projects],
        statuses=PROJECT_STATUSES,
        currency=settings_for_client()["currency"],
    )


def _detail(project):
    client = project.client
    can_assign = g.user.sees_all
    body = {
        "project": project.to_dict(detail=True),
        "client": {"id": client.id, "name": client.name, "contact_name": client.contact_name, "phone": client.phone},
        "statuses": PROJECT_STATUSES,
        "currency": settings_for_client()["currency"],
        "can_assign_manager": can_assign,
    }
    if can_assign:
        managers = User.query.filter_by(role_key="project_manager", is_active=True).order_by(User.name).all()
        body["managers"] = [{"code": u.code, "name": u.name} for u in managers]
    return body


@bp.get("/api/projects/<int:project_id>")
def get_project(project_id):
    return jsonify(_detail(_project_or_404(project_id)))


@bp.patch("/api/projects/<int:project_id>")
def update_project(project_id):
    project = _project_or_404(project_id)
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")

    f = Fields(payload)
    f.text("title", 160, required=True, label="a project title")
    f.choice("status", PROJECT_STATUSES)
    f.text("work_category", 120)
    f.text("work_order_no", 60)
    f.date("work_order_date")
    f.date("start_date")
    f.integer("completion_days", 0, 3650)
    f.money("estimated_amount")
    f.money("discount_amount", nullable=False)
    f.text("payment_terms", 5000)
    f.text("special_terms", 5000)
    f.text("site_state", 80)
    f.text("site_district", 80)
    f.text("site_city", 120)
    f.text("site_address", 400)
    f.text("site_pincode", 6)
    errors, data = f.errors, f.data

    if data.get("site_pincode") and not PINCODE_RE.fullmatch(data["site_pincode"]):
        errors["site_pincode"] = "Enter a 6-digit pincode"

    if "manager_code" in payload:
        code = payload["manager_code"] or None
        if code != project.manager_code:
            if not g.user.sees_all:
                abort(403, "Only the admin can assign the project manager.")
            manager = db.session.get(User, code) if code else None
            if code and not (manager and manager.is_active and manager.role_key == "project_manager"):
                errors["manager_code"] = "Choose a project manager from the list"
            else:
                data["manager_code"] = code

    payments = None
    if "payments" in payload:
        payments = _payments(payload["payments"], errors)

    estimated = data["estimated_amount"] if "estimated_amount" in data else project.estimated_amount
    discount = data["discount_amount"] if "discount_amount" in data else (project.discount_amount or Decimal(0))
    if "estimated_amount" not in errors and "discount_amount" not in errors and estimated is not None:
        if discount > estimated:
            errors["discount_amount"] = "The discount cannot be more than the estimated amount"
        elif payments is not None and "payments" not in errors:
            if sum((p["amount"] for p in payments), Decimal(0)) > estimated - discount:
                errors["payments"] = "The payment steps add up to more than the net amount"

    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    for key, value in data.items():
        setattr(project, key, value)
    if payments is not None:
        project.payments = [
            ProjectPayment(label=p["label"], amount=p["amount"], due_date=p["due_date"], position=i)
            for i, p in enumerate(payments, start=1)
        ]
    db.session.commit()
    return jsonify(_detail(project))

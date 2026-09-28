"""Projects (the Project Management service): work orders, amounts, terms and the payment schedule.
A project normally starts from a won lead (create_project_from_lead) and is then completed by the project
manager or the admin. Work that is already running can be added directly (create_project)."""

import re
from decimal import Decimal

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy import func
from werkzeug.exceptions import abort

from .auth import visible_clients, visible_projects
from .extensions import db
from .models import Activity, Attendance, Client, Project, ProjectPayment, User, WorkerAttendance, settings_for_client, utcnow
from .modules import check_module
from .reference_data import PROJECT_STATUSES
from .timeutil import to_local
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
    """Turn a won lead into a project. If the lead was raised for an existing client (lead.client_id -
    someone adding a new project for a client they already have), that client just gains another project;
    otherwise a client is created (reusing one with the same name if there is one). Returns (project, reused)."""
    if lead.stage != "Won":
        raise ProjectError("Only a won lead can become a project.")
    if lead.project is not None:
        raise ProjectError("This lead already has a project.", 409)

    owner = lead.owner_code or user.code
    name = lead.company or lead.contact_name

    if lead.client_id is not None:
        client = lead.client
        reused = True
    else:
        client = Client.query.filter(func.lower(Client.name) == name.lower()).first()
        reused = client is not None
        if client is None:
            client = Client(
                name=name, contact_name=lead.contact_name if lead.company else "", phone=lead.phone, email=lead.email,
                site_category=lead.site_category, pincode=lead.site_pincode, state=lead.site_state,
                district=lead.site_district, city=lead.site_city, address=lead.site_address, owner_code=owner,
            )
            db.session.add(client)

    service_names = [s.name for s in lead.services] if lead.services else ([lead.service] if lead.service else [])
    title = f"{client.name} - {', '.join(service_names)}" if service_names else client.name
    latest_round = max(lead.negotiations, key=lambda n: n.round_no, default=None)
    estimated_amount = (latest_round.estimate if latest_round and latest_round.estimate is not None else None) or lead.est_value

    project = Project(
        client=client, lead=lead, title=title,
        work_category=lead.service, services=list(lead.services), estimated_amount=estimated_amount, owner_code=owner,
        site_pincode=lead.site_pincode, site_state=lead.site_state, site_district=lead.site_district,
        site_city=lead.site_city, site_address=lead.site_address,
    )
    db.session.add(project)
    db.session.flush()
    lead.activities.insert(0, Activity(kind="project", text=f"Project {project.code} created"))
    return project, reused


def brought_by(lead, added_by=None):
    """Who brought the work in: the staff member who took the enquiry ("Enquired by" on the lead), else
    whoever entered the lead, else whoever added it by hand (added_by). None when nobody is recorded."""
    if lead is not None and lead.enquired_by is not None:
        return {"name": lead.enquired_by.name, "how": "Took the enquiry"}
    if lead is not None and lead.owner is not None:
        return {"name": lead.owner.name, "how": "Entered the lead"}
    if added_by is not None:
        return {"name": added_by.name, "how": "Added it"}
    return None


def _team(project):
    """Everyone whose attendance was recorded against this project - app users checking in to it, and
    manpower/staff whose WhatsApp attendance matched it - with how many days and their latest one, most
    days first."""
    people = {}

    def add(key, name, kind, day):
        row = people.setdefault(key, {"name": name, "kind": kind, "days": 0, "last_day": None})
        row["days"] += 1
        row["last_day"] = max(row["last_day"] or day, day)

    for a in Attendance.query.filter_by(project_id=project.id):
        add(("user", a.user_code), a.user.name, "App user", a.work_date)
    for a in WorkerAttendance.query.filter_by(project_id=project.id, status="present"):
        add(("worker", a.worker_id), a.worker.name, a.worker.category.capitalize(), a.work_date)
    rows = sorted(people.values(), key=lambda r: (-r["days"], r["name"].lower()))
    return [{**r, "last_day": r["last_day"].isoformat()} for r in rows]


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
    settings = settings_for_client()
    return jsonify(
        projects=[p.to_dict() for p in projects],
        statuses=PROJECT_STATUSES,
        currency=settings["currency"],
        services=settings["services"],                      # for the Add project form
        clients=[{"id": c.id, "name": c.name} for c in visible_clients().order_by(Client.name)],
    )


@bp.post("/api/projects")
def create_project():
    """Add a project that did not come from a lead (for example one that is already running).
    Pick an existing client or give the name of a new one; the rest is filled in on the project screen."""
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")

    f = Fields(payload)
    f.text("title", 160)
    f.text("work_category", 120)
    f.text("new_client_name", 160)
    f.choice("status", PROJECT_STATUSES)
    errors = dict(f.errors)

    client = None
    raw_id = payload.get("client_id")
    if raw_id not in (None, ""):
        try:
            client = visible_clients().filter(Client.id == int(raw_id)).first()
        except (TypeError, ValueError):
            client = None
        if client is None:
            errors["client_id"] = "Choose a client from the list"
    else:
        name = f.data.get("new_client_name", "")
        if not name:
            errors["client_id"] = "Choose a client, or enter the name of a new one"
        else:
            client = Client.query.filter(func.lower(Client.name) == name.lower()).first() or Client(name=name, owner_code=g.user.code)

    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    category = f.data.get("work_category", "")
    title = f.data.get("title") or (f"{client.name} - {category}" if category else client.name)
    project = Project(
        client=client, title=title[:160], work_category=category, status=f.data.get("status", "running"),
        owner_code=g.user.code,
        manager_code=g.user.code if g.user.role_key == "project_manager" else None,   # a manager who adds it runs it
    )
    db.session.add(project)
    db.session.commit()
    return jsonify(_detail(project)), 201


def _detail(project):
    client = project.client
    can_assign = g.user.sees_all
    body = {
        "project": project.to_dict(detail=True),
        "client": {"id": client.id, "name": client.name, "contact_name": client.contact_name, "phone": client.phone},
        "statuses": PROJECT_STATUSES,
        "currency": settings_for_client()["currency"],
        "can_assign_manager": can_assign,
        "dashboard": {
            # "Running for" counts from the start date when one is set, else from when the project was added.
            "started": (project.start_date or to_local(project.created_at).date()).isoformat(),   # local day, not UTC
            "start_date_set": project.start_date is not None,
            "completed_at": project.completed_at.isoformat() + "Z" if project.completed_at else None,
            "brought_by": brought_by(project.lead, project.owner),
            "team": _team(project),
            "can_close": g.user.is_admin,
            "can_delete": g.user.is_admin,          # TEMPORARY - for the backfill, see delete_project
        },
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
    if project.status == "completed" and project.completed_at is None:
        project.completed_at = utcnow()
    elif project.status != "completed":
        project.completed_at = None
    if payments is not None:
        project.payments = [
            ProjectPayment(label=p["label"], amount=p["amount"], due_date=p["due_date"], position=i)
            for i, p in enumerate(payments, start=1)
        ]
    db.session.commit()
    return jsonify(_detail(project))


@bp.post("/api/projects/<int:project_id>/close")
def close_project(project_id):
    """Close a project (mark it completed). Admin only - the project's own screen shows the button to the
    admin alone, and this refuses everyone else too."""
    if not g.user.is_admin:
        abort(403, "Only the admin can close a project.")
    project = _project_or_404(project_id)
    if project.status == "completed":
        return jsonify(error="This project is already closed."), 409
    project.status = "completed"
    project.completed_at = utcnow()
    db.session.commit()
    return jsonify(_detail(project))


@bp.delete("/api/projects/<int:project_id>")
def delete_project(project_id):
    """TEMPORARY - lets the admin clear out wrong or test projects while old work is being backfilled.
    Remove this route and the Delete project button once the backfill is done. Its payment schedule goes
    with it; attendance that pointed at it stays, with no project; a won lead it came from can be made
    into a project again."""
    if not g.user.is_admin:
        abort(403, "Only the admin can delete a project.")
    project = _project_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    return "", 204

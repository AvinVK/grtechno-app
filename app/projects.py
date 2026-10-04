"""Projects (the Project Management service): work orders, amounts, terms and the payment schedule.
A project normally starts from a won lead (create_project_from_lead) and is then completed by the project
manager or the admin. Work that is already running can be added directly (create_project)."""

import re
from decimal import Decimal

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy import func
from werkzeug.exceptions import abort

from .auth import visible_clients, visible_projects
from .constants import PAYMENT_MODES
from .extensions import db
from .models import Activity, Attendance, Client, Project, ProjectPayment, Service, User, WorkerAttendance, settings_for_client, utcnow
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
    """Turn a won lead into a project. Winning is the moment the admin maps it to a client - either an
    existing one (lead.client_id, set on the same request that moved it to Won) or a brand-new one, never
    guessed by matching names, so two enquiries that happen to share a name never merge on their own.
    Returns (project, reused)."""
    if lead.stage != "Won":
        raise ProjectError("Only a won lead can become a project.")
    if lead.project is not None:
        raise ProjectError("This lead already has a project.", 409)

    owner = lead.owner_code or user.code
    name = lead.company or lead.contact_name
    survey = lead.survey  # set by now - Won requires the site survey step, which is where site details live

    if lead.client_id is not None:
        client = lead.client
        reused = True
    else:
        client = Client(
            name=name, contact_name=lead.contact_name if lead.company else "", phone=lead.phone, email=lead.email,
            site_category=survey.site_category if survey else "", pincode=survey.site_pincode if survey else "",
            state=survey.site_state if survey else "", district=survey.site_district if survey else "",
            city=survey.site_city if survey else "", address=survey.site_address if survey else "", owner_code=owner,
        )
        db.session.add(client)
        reused = False

    # The site name is what tells this project apart from another at the same client (a client can go on
    # to have more than one), so it leads the title whenever the survey captured one.
    service_names = [s.name for s in lead.services] if lead.services else ([lead.service] if lead.service else [])
    if survey and survey.site_name:
        title = survey.site_name
    elif service_names:
        title = f"{client.name} - {', '.join(service_names)}"
    else:
        title = client.name
    latest_round = max(lead.negotiations, key=lambda n: n.round_no, default=None)
    estimated_amount = (latest_round.estimate if latest_round and latest_round.estimate is not None else None) or lead.est_value

    project = Project(
        client=client, lead=lead, title=title,
        work_category=lead.service, services=list(lead.services), estimated_amount=estimated_amount, owner_code=owner,
        site_name=survey.site_name if survey else "",
        site_pincode=survey.site_pincode if survey else "", site_state=survey.site_state if survey else "",
        site_district=survey.site_district if survey else "", site_city=survey.site_city if survey else "",
        site_address=survey.site_address if survey else "",
        work_order_no=lead.work_order_no, work_order_date=lead.work_order_date,
    )
    # The advance that won the lead is the project's first payment step, already received - it carries
    # over so the project doesn't start its payment schedule from a blank page.
    if lead.advance_amount is not None:
        project.payments.append(ProjectPayment(
            label="Advance", amount=lead.advance_amount, due_date=lead.advance_date, position=1,
            mode=lead.advance_mode, paid_date=lead.advance_date, comments=lead.advance_comments,
        ))
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
    project = visible_projects().filter(Project.id == project_id).first()
    if project is None:
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
        f.date("paid_date")
        f.text("comments", 2000)
        if isinstance(item, dict) and item.get("mode") not in (None, "", *PAYMENT_MODES):
            f.errors["mode"] = "Choose one of the payment modes"
        problems = dict(f.errors)
        amount = parse_money(item.get("amount", 0) if isinstance(item, dict) else 0, problems, "amount")
        if problems:
            errors["payments"] = f"Payment step {i}: {next(iter(problems.values()))}"
            return None
        rows.append({
            "label": f.data["label"], "amount": amount, "due_date": f.data.get("due_date"),
            "mode": (item.get("mode") or "") if isinstance(item, dict) else "",
            "paid_date": f.data.get("paid_date"), "comments": f.data.get("comments", ""),
        })
    return rows


@bp.get("/projects")
def page():
    title = "Projects" if g.user.sees_all else "My projects"
    return render_template("projects.html", page_title=title)


@bp.get("/api/projects")
def list_projects():
    projects = visible_projects().order_by(Project.id.desc()).all()
    settings = settings_for_client()
    return jsonify(
        projects=[p.to_dict() for p in projects],
        statuses=PROJECT_STATUSES,
        currency=settings["currency"],
        services=settings["services"],                      # for the Add project form
        payment_modes=PAYMENT_MODES,
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
    f.text("site_name", 160)
    f.text("new_client_name", 160)
    f.text("new_contact_name", 120)
    f.text("new_phone", 40)
    f.choice("status", PROJECT_STATUSES)
    f.money("estimated_amount")
    f.text("work_order_no", 60)
    f.date("work_order_date")
    f.money("advance_amount")
    f.date("advance_date")
    f.text("advance_comments", 2000)
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
            client = Client.query.filter(func.lower(Client.name) == name.lower()).first() or Client(
                name=name, owner_code=g.user.code,
                contact_name=f.data.get("new_contact_name", ""), phone=f.data.get("new_phone", ""))

    raw_services = payload.get("services")
    names = [s for s in dict.fromkeys(raw_services or []) if isinstance(s, str)] if isinstance(raw_services, list) else []
    services = Service.query.filter(Service.name.in_(names)).all() if names else []
    if len(services) != len(names):
        errors["services"] = "Choose valid services"

    estimated = f.data.get("estimated_amount")
    advance = f.data.get("advance_amount")
    advance_mode = payload.get("advance_mode") or None
    if advance is not None:
        if not f.data.get("advance_date"):
            errors["advance_date"] = "This field is required"
        if advance_mode not in PAYMENT_MODES:
            errors["advance_mode"] = "Choose how the advance was paid"
        if estimated is not None and advance > estimated:
            errors["advance_amount"] = "The advance cannot be more than the estimated amount"

    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    service_names = [s.name for s in services]
    site_name = f.data.get("site_name", "")
    title = site_name or f.data.get("title") or (f"{client.name} - {', '.join(service_names)}" if service_names else client.name)
    project = Project(
        client=client, title=title[:160], site_name=site_name, work_category=", ".join(service_names), services=services,
        status=f.data.get("status", "running"), estimated_amount=estimated,
        work_order_no=f.data.get("work_order_no", ""), work_order_date=f.data.get("work_order_date"),
        owner_code=g.user.code,
        manager_code=g.user.code if g.user.role_key == "project_manager" else None,   # a manager who adds it runs it
    )
    if advance is not None:
        project.payments.append(ProjectPayment(
            label="Advance", amount=advance, due_date=f.data["advance_date"], paid_date=f.data["advance_date"],
            position=1, mode=advance_mode, comments=f.data.get("advance_comments", ""),
        ))
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
        "payment_modes": PAYMENT_MODES,
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
    f.text("site_name", 160, required=True, label="the site name")
    f.choice("status", PROJECT_STATUSES)
    f.text("work_category", 120)
    f.text("work_order_no", 60)
    f.date("work_order_date")
    f.date("start_date")
    f.integer("completion_days", 0, 3650)
    f.money("estimated_amount")
    f.money("discount_amount", nullable=False)
    f.money("final_amount")
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
    final = data["final_amount"] if "final_amount" in data else project.final_amount
    if "estimated_amount" not in errors and "discount_amount" not in errors and estimated is not None:
        if discount > estimated:
            errors["discount_amount"] = "The discount cannot be more than the estimated amount"

    # Once a final measurement is in, it's the ceiling the schedule is checked against - not the
    # pre-measurement negotiated figure, which the final amount can come in above or below.
    net_ceiling = final if final is not None else (estimated - discount if estimated is not None else None)
    if "final_amount" not in errors and net_ceiling is not None and payments is not None and "payments" not in errors:
        if sum((p["amount"] for p in payments), Decimal(0)) > net_ceiling:
            errors["payments"] = "The payment steps add up to more than the net amount"

    # Same gate as the dedicated close route (see close_project) - status is just another field here, but
    # completing a project still needs the final measurement on file and fully paid either way.
    if data.get("status") == "completed" and project.status != "completed" and "status" not in errors:
        if final is None:
            errors["status"] = "Enter the final measurement amount before closing."
        elif project.paid_amount < final:
            errors["status"] = "The final amount hasn't been fully paid yet."

    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    # Recording the final measurement for the first time is itself a status move, same idea as entering
    # the work order moves a lead to its own next stage - unless this same request already said otherwise.
    newly_measured = "final_amount" in data and data["final_amount"] is not None and project.final_amount is None
    if newly_measured and "status" not in data and project.status != "completed":
        data["status"] = "final_estimate_sent"

    # The site name is the project's title - whichever one is sent, both are set to it.
    if "site_name" in data:
        data["title"] = data["site_name"]
    elif "title" in data:
        data["site_name"] = data["title"]
    for key, value in data.items():
        setattr(project, key, value)
    if project.status == "completed" and project.completed_at is None:
        project.completed_at = utcnow()
    elif project.status != "completed":
        project.completed_at = None
    if payments is not None:
        project.payments = [
            ProjectPayment(
                label=p["label"], amount=p["amount"], due_date=p["due_date"], position=i,
                mode=p["mode"], paid_date=p["paid_date"], comments=p["comments"],
            )
            for i, p in enumerate(payments, start=1)
        ]
    db.session.commit()
    return jsonify(_detail(project))


@bp.post("/api/projects/<int:project_id>/close")
def close_project(project_id):
    """Close a project (mark it completed). Admin only - the project's own screen shows the button to the
    admin alone, and this refuses everyone else too. Needs the final measurement's amount on file (set via
    PATCH final_amount) and that amount fully paid - the sheet that collects both keeps this from firing
    before either is true, but the gate lives here too since that's just the UI's say-so."""
    if not g.user.is_admin:
        abort(403, "Only the admin can close a project.")
    project = _project_or_404(project_id)
    if project.status == "completed":
        return jsonify(error="This project is already closed."), 409
    if project.final_amount is None:
        abort(422, "Enter the final measurement amount before closing.")
    if project.paid_amount < project.final_amount:
        abort(422, "The final amount hasn't been fully paid yet.")
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

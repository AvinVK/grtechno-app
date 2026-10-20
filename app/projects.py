"""Projects (the Project Management service): work orders, amounts, terms and the payment schedule.
A project normally starts from a won lead (create_project_from_lead) and is then completed by the project
manager or the admin. Work that is already running can be added directly (create_project)."""

import re
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy import func
from werkzeug.exceptions import abort

from . import inventory as inv
from .auth import PROJECT_MANAGER_ROLE_KEYS, visible_clients, visible_projects
from .constants import COMMISSION_ROLE_KEY, PAYMENT_MODES
from .extensions import db
from .models import Activity, Attendance, Client, Material, MaterialMovement, Project, ProjectExpense, ProjectPayment, Service, User, Worker, WorkerAttendance, settings_for_client, utcnow
from .modules import check_module
from .reference_data import PROJECT_STATUSES
from .timeutil import to_local, today_local
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

    # Only an approved day counts (see Attendance.status) - a pending one isn't a verified day's work yet.
    for a in Attendance.query.filter_by(project_id=project.id, status="approved"):
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
        manager_code=g.user.code if g.user.role_key in PROJECT_MANAGER_ROLE_KEYS else None,   # a manager who adds it runs it
    )
    if advance is not None:
        project.payments.append(ProjectPayment(
            label="Advance", amount=advance, due_date=f.data["advance_date"], paid_date=f.data["advance_date"],
            position=1, mode=advance_mode, comments=f.data.get("advance_comments", ""),
        ))
    db.session.add(project)
    db.session.commit()
    return jsonify(_detail(project)), 201


def _material_costs(project):
    """What's been issued to this project, net of anything sent back (Inventory's own stock ledger - see
    app/inventory.py), for the Materials tab: one row per approved issue or return, at whatever rate the
    stock actually cost at the time, same figures Inventory itself shows. A return's own amount comes back
    negative, so the total nets out on its own (kohal, 2026-10-20: "some of them are not used in the
    project, so there should be a return to inventory request as well" - the project's own cost should
    drop back down once material it never used is sent back). Not gated on the Inventory module - this is
    the project's own expense, not a stock-management action. A still-pending or rejected request never
    moved stock either way (see MaterialMovement.status), so it isn't a real cost yet and stays off this
    list - see material_requests for those."""
    movements = (
        MaterialMovement.query.filter_by(project_id=project.id, status="approved")
        .filter(MaterialMovement.kind.in_(("out", "in")))
        .order_by(MaterialMovement.entry_date.desc(), MaterialMovement.id.desc())
        .all()
    )
    rows = [{
        "id": mv.id, "material_id": mv.material_id, "material_name": mv.material.name,
        "material_code": mv.material.code, "unit": mv.material.unit, "kind": mv.kind,
        "quantity": float(mv.quantity), "rate": float(mv.rate),
        "amount": float(mv.amount) if mv.kind == "out" else -float(mv.amount),
        "entry_date": mv.entry_date.isoformat(), "note": mv.note,
        "given_by_name": mv.given_by.name if mv.given_by else None,
    } for mv in movements]
    total = sum((Decimal(str(r["amount"])) for r in rows), start=Decimal("0"))
    return rows, float(total)


def _expenses(project):
    """Money paid out of this project, not to the client - commission for now (kohal, 2026-10-18), with
    food meant to join it later as more ProjectExpense.kind values (daily wages are computed instead, see
    _wage_expenses below, rather than entered here). One row per entry, same shape as _material_costs above."""
    rows = [e.to_dict() for e in project.expenses]
    total = float(sum((e.amount for e in project.expenses), start=Decimal("0")))
    return rows, total


def _wage_expenses(project):
    """A daily-wage worker's cost on this project, computed rather than entered (kohal, 2026-10-20: "for
    every daily wages worker, admin has entered the daily wage amount... if the worker checks in project 1
    on day 1,2,3, then the total expense will be = (daily wages*3)") - their day rate times how many distinct
    days they're recorded present here, from whichever source actually has them: their own app check-in
    (Attendance) or a WhatsApp day logged for them (WorkerAttendance), the same two sources _team above
    combines - deduped by date so a day caught by both is never paid twice. Only employment_type ==
    'daily_wages' workers with a wage_amount set are counted; a salaried worker's attendance isn't
    project-costed this way."""
    rows = []
    workers = Worker.query.filter_by(employment_type="daily_wages").filter(Worker.wage_amount.isnot(None)).all()
    for w in workers:
        days = {a.work_date for a in WorkerAttendance.query.filter_by(
            project_id=project.id, worker_id=w.id, status="present")}
        if w.user_code:
            days.update(a.work_date for a in Attendance.query.filter_by(
                project_id=project.id, user_code=w.user_code, status="approved"))
        if not days:
            continue
        amount = (w.wage_amount * len(days)).quantize(Decimal("0.01"))
        rows.append({
            "worker_id": w.id, "worker_name": w.name, "days": len(days),
            "wage_amount": float(w.wage_amount), "amount": float(amount),
        })
    rows.sort(key=lambda r: r["worker_name"].lower())
    total = float(sum((Decimal(str(r["amount"])) for r in rows), start=Decimal("0")))
    return rows, total


def _detail(project):
    client = project.client
    can_assign = g.user.sees_all
    materials, total_material_cost = _material_costs(project)
    expenses, total_expense = _expenses(project)
    wage_expenses, total_wage_expense = _wage_expenses(project)
    body = {
        "project": project.to_dict(detail=True),
        "client": {"id": client.id, "name": client.name, "contact_name": client.contact_name, "phone": client.phone},
        "statuses": PROJECT_STATUSES,
        "currency": settings_for_client()["currency"],
        "payment_modes": PAYMENT_MODES,
        "can_assign_manager": can_assign,
        "materials": materials,
        "total_material_cost": total_material_cost,
        "expenses": expenses,
        "total_expense": total_expense,
        "wage_expenses": wage_expenses,
        "total_wage_expense": total_wage_expense,
        # For the commission form's worker picker - only someone in that role earns it (kohal, 2026-10-18).
        "commission_workers": [{"id": w.id, "name": w.name}
                                for w in Worker.query.filter_by(role_key=COMMISSION_ROLE_KEY).order_by(Worker.name)],
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
        managers = User.query.filter(User.role_key.in_(PROJECT_MANAGER_ROLE_KEYS), User.is_active.is_(True)).order_by(User.name).all()
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
            if code and not (manager and manager.is_active and manager.role_key in PROJECT_MANAGER_ROLE_KEYS):
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


# ---------- material requests (kohal, 2026-10-16, updated 2026-10-17, 2026-10-19, 2026-10-20) ----------
#
# Asking for material against a project - or asking for some of it back (kohal, 2026-10-20: "whatever
# material is requested by the site supervisor, some of them are not used in the project, so there should
# be a return to inventory request as well but the quantity and material source will be whatever is present
# in the project") - lives here, gated by the Projects module like everything else on this page. Approving
# either doesn't, any more - see app/inventory.py's own Material requests tab (material_requests/
# approve_material_request there) - anyone with Inventory access can, except whoever asked for it in the
# first place (kohal, 2026-10-19: "creator user cannot be approval"), and recording who physically handled
# it, how, and when is an Inventory-side action either way. This project page just shows what's pending,
# read-only, and lets anyone who can see the project ask for more or send some back.

def _material_request_dict(movement):
    d = movement.to_dict()
    d["material_name"] = movement.material.name
    d["material_code"] = movement.material.code
    d["unit"] = movement.material.unit
    return d


def _net_issued(project_id, material_id):
    """How much of this material is still out at this project right now - approved issues minus whatever's
    already been approved back, both scoped to this project+material. Caps a return request so it can never
    ask for more than the project could possibly still be holding."""
    out_qty = (db.session.query(func.coalesce(func.sum(MaterialMovement.quantity), 0))
               .filter_by(project_id=project_id, material_id=material_id, kind="out", status="approved").scalar())
    in_qty = (db.session.query(func.coalesce(func.sum(MaterialMovement.quantity), 0))
              .filter_by(project_id=project_id, material_id=material_id, kind="in", status="approved").scalar())
    return Decimal(out_qty) - Decimal(in_qty)


@bp.get("/api/projects/<int:project_id>/material-requests")
def material_requests(project_id):
    """Pending (not yet approved or rejected) issue and return requests for this project, the active
    material list to request from, and - for the return form specifically - only materials this project
    actually still has some of (kohal: "the quantity and material source will be whatever is present in
    the project"), each with how much of it could still be sent back."""
    project = _project_or_404(project_id)
    pending = (MaterialMovement.query.filter_by(project_id=project.id, status="pending")
               .filter(MaterialMovement.kind.in_(("out", "in")))
               .order_by(MaterialMovement.created_at).all())
    issued_material_ids = {
        mv.material_id for mv in
        MaterialMovement.query.filter_by(project_id=project.id, kind="out", status="approved")
    }
    returnable = []
    for material_id in issued_material_ids:
        cap = _net_issued(project.id, material_id)
        if cap <= 0:
            continue
        material = db.session.get(Material, material_id)
        if material is None:
            continue
        returnable.append({"id": material.id, "code": material.code, "name": material.name,
                            "unit": material.unit, "returnable_qty": float(cap)})
    returnable.sort(key=lambda r: r["name"])
    return jsonify(
        requests=[_material_request_dict(mv) for mv in pending],
        materials=[{"id": m.id, "code": m.code, "name": m.name, "unit": m.unit, "stock_qty": float(m.stock_qty)}
                   for m in Material.query.filter_by(is_active=True).order_by(Material.name)],
        returnable_materials=returnable,
    )


@bp.post("/api/projects/<int:project_id>/material-requests")
def request_material(project_id):
    """Ask for material to be issued to this project, or sent back from it (kohal, 2026-10-20: "there
    should be a return to inventory request as well") - `kind: "in"` for a return, anything else (or left
    out) defaults to the usual issue request. Always waits for someone else to approve it from Inventory's
    own Material requests tab (kohal, 2026-10-19: "it should not be auto approved... creator user cannot be
    approval") - no self-approval shortcut here any more, not even for whoever already has Inventory access
    themselves; see app/inventory.py's approve_material_request, which also refuses the requester their own
    approval if they try it directly."""
    project = _project_or_404(project_id)
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")

    kind = "in" if payload.get("kind") == "in" else "out"
    f = Fields(payload)
    f.money("quantity", nullable=False)
    f.text("note", 200)
    errors = f.errors

    material = None
    raw_id = payload.get("material_id")
    if str(raw_id).isdigit():
        material = db.session.get(Material, int(raw_id))
    if material is None or not material.is_active:
        errors["material_id"] = "Pick a material"

    qty = f.data.get("quantity")
    if qty is None:
        errors.setdefault("quantity", "Enter a quantity greater than 0")
    elif qty <= 0:
        errors["quantity"] = "Enter a quantity greater than 0"
    elif kind == "in" and material is not None:
        # Unlike an issue - asking for more than what's in stock is fine there, that's the point of a
        # request someone else has to approve (kohal, 2026-10-17) - a return can't claim more than the
        # project could possibly still be holding (kohal, 2026-10-20: "whatever is present in the
        # project").
        cap = _net_issued(project.id, material.id)
        if qty > cap:
            errors["quantity"] = f"Only {cap} {material.unit or ''} from this project can be returned".strip()
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    rate = material.avg_rate
    movement = MaterialMovement(
        material=material, kind=kind, quantity=qty, rate=rate, amount=qty * rate,
        project_id=project.id, note=f.data.get("note", ""), entry_date=today_local(),
        created_by_code=g.user.code, requested=True,
        **inv._status_fields(False),
    )
    db.session.add(movement)
    db.session.commit()
    return jsonify(request=_material_request_dict(movement)), 201


# ---------- commission (kohal, 2026-10-18) ----------
#
# "the person assigned to [Project manager Chandrapur] gets commission on the negotiated amount of the
# project... in payment subtab under project, i need to enter what percentage of commission was given to
# whom and that should go towards project expense" - the first kind of ProjectExpense; see that model's own
# docstring for why it's one table rather than a commission-only one. Moved from the Payment tab to its own
# Expense tab (kohal, 2026-10-20), alongside the computed daily-wage figures from _wage_expenses - these
# routes themselves are unchanged, only where the frontend shows the form.

def _expense_fields(payload):
    """worker (a Worker in the commission role), percent, entry_date and note from the request - shared by
    add_expense and update_expense. Returns (worker, percent, data, errors); percent is a Decimal or None."""
    f = Fields(payload)
    f.date("entry_date")
    f.text("note", 2000)
    errors = f.errors

    worker = None
    raw_worker = payload.get("worker_id")
    if str(raw_worker).isdigit():
        worker = db.session.get(Worker, int(raw_worker))
    if worker is None or worker.role_key != COMMISSION_ROLE_KEY:
        errors["worker_id"] = "Pick a project manager (Chandrapur)"

    percent = None
    raw_percent = payload.get("percent")
    if raw_percent in (None, ""):
        errors.setdefault("percent", "Enter the commission percentage")
    else:
        try:
            percent = Decimal(str(raw_percent))
        except InvalidOperation:
            errors["percent"] = "Enter a number"
        else:
            if not percent.is_finite() or percent <= 0 or percent > 100:
                errors["percent"] = "Enter a percentage from 0 to 100"

    if not f.data.get("entry_date") and "entry_date" not in f.errors:
        f.data["entry_date"] = today_local()

    return worker, percent, f.data, errors


@bp.post("/api/projects/<int:project_id>/expenses")
def add_expense(project_id):
    """Record a cut of this project's negotiated amount paid out as commission. The rupee amount is
    computed from the project's own net_amount right now and then fixed - see ProjectExpense's own
    docstring for why editing the project's amount later doesn't move what's already been recorded."""
    project = _project_or_404(project_id)
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    worker, percent, data, errors = _expense_fields(payload)
    if project.net_amount is None:
        errors.setdefault("percent", "Set the project's negotiated amount first, on its Payment tab")
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    basis = project.net_amount
    expense = ProjectExpense(
        project=project, kind="commission", worker=worker, percent=percent, basis_amount=basis,
        amount=(basis * percent / Decimal("100")).quantize(Decimal("0.01")),
        entry_date=data["entry_date"], note=data.get("note", ""), created_by_code=g.user.code,
    )
    db.session.add(expense)
    db.session.commit()
    return jsonify(_detail(project)), 201


@bp.patch("/api/projects/<int:project_id>/expenses/<int:expense_id>")
def update_expense(project_id, expense_id):
    project = _project_or_404(project_id)
    expense = ProjectExpense.query.filter_by(id=expense_id, project_id=project.id).first()
    if expense is None:
        abort(404)
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    worker, percent, data, errors = _expense_fields(payload)
    if project.net_amount is None:
        errors.setdefault("percent", "Set the project's negotiated amount first, on its Payment tab")
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    basis = project.net_amount
    expense.worker = worker
    expense.percent = percent
    expense.basis_amount = basis
    expense.amount = (basis * percent / Decimal("100")).quantize(Decimal("0.01"))
    expense.entry_date = data["entry_date"]
    expense.note = data.get("note", "")
    db.session.commit()
    return jsonify(_detail(project))


@bp.delete("/api/projects/<int:project_id>/expenses/<int:expense_id>")
def delete_expense(project_id, expense_id):
    project = _project_or_404(project_id)
    expense = ProjectExpense.query.filter_by(id=expense_id, project_id=project.id).first()
    if expense is None:
        abort(404)
    db.session.delete(expense)
    db.session.commit()
    return jsonify(_detail(project))

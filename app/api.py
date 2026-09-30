import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen

from flask import Blueprint, g, jsonify, request
from werkzeug.exceptions import HTTPException, abort

from .auth import visible_clients, visible_leads
from .modules import check_module, modules_for
from .projects import ProjectError, create_project_from_lead
from .constants import CLOSED_STAGES, LOST, OPEN_STAGES, STAGES, WON
from .extensions import db
from .models import (
    Activity, Client, Lead, LeadNegotiation, LeadSurvey, Pincode, Service, SurveyPhoto,
    Worker, settings_for_client, utcnow,
)
from .timeutil import to_local, today_local
from .uploads import UploadError, delete_upload, save_upload

bp = Blueprint("api", __name__, url_prefix="/api")

TEXT_LIMITS = {
    "contact_name": 120,
    "company": 160,
    "phone": 40,
    "email": 160,
    "service": 120,
    "source": 120,
    "notes": 5000,
    "work_order_no": 60,
}
MAX_VALUE = Decimal("99999999999")
PINCODE_RE = re.compile(r"[1-9][0-9]{5}")
PINCODE_SERVICE = "https://api.postalpincode.in/pincode/"


@bp.errorhandler(HTTPException)
def json_error(err):
    return jsonify(error=err.description or err.name), err.code


@bp.before_request
def _leads_service():
    if request.endpoint != "api.pincode_lookup":          # a general helper: any signed-in person may use it
        check_module("leads")


def _payload() -> dict:
    # Requiring JSON also blocks cross-site form posts (they cannot send this content type).
    if not request.is_json:
        abort(415, "Send JSON")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "Send a JSON object")
    return data


def _parse_date_field(payload, data, errors, field):
    if field not in payload:
        return
    raw = payload[field]
    if raw in (None, ""):
        data[field] = None
    else:
        try:
            data[field] = date.fromisoformat(str(raw))
        except ValueError:
            errors[field] = "Pick a valid date"


def _parse_amount_field(payload, data, errors, field):
    if field not in payload:
        return
    raw = payload[field]
    if raw is None or raw == "":
        data[field] = None
    else:
        try:
            amount = Decimal(str(raw))
            if not amount.is_finite() or amount < 0 or amount > MAX_VALUE:
                raise InvalidOperation
            data[field] = amount.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            errors[field] = "Enter a number, 0 or more"


def _validate(payload: dict) -> tuple[dict, dict]:
    """Return (clean values for the fields present, errors by field)."""
    data, errors = {}, {}

    for field, limit in TEXT_LIMITS.items():
        if field not in payload:
            continue
        value = payload[field]
        if value is None:
            value = ""
        if not isinstance(value, str):
            errors[field] = "Enter text"
            continue
        value = value.strip()
        if len(value) > limit:
            errors[field] = f"Keep this under {limit} characters"
            continue
        data[field] = value

    if "est_value" in payload:
        raw = payload["est_value"]
        if raw is None or raw == "":
            data["est_value"] = None
        else:
            try:
                amount = Decimal(str(raw))
                if not amount.is_finite() or amount < 0 or amount > MAX_VALUE:
                    raise InvalidOperation
                data["est_value"] = amount.quantize(Decimal("0.01"))
            except (InvalidOperation, ValueError):
                errors["est_value"] = "Enter a number, 0 or more"

    if "follow_up_date" in payload:
        raw = payload["follow_up_date"]
        if raw in (None, ""):
            data["follow_up_date"] = None
        else:
            try:
                data["follow_up_date"] = date.fromisoformat(str(raw))
            except ValueError:
                errors["follow_up_date"] = "Pick a valid date"

    if "quote_sent_date" in payload:
        raw = payload["quote_sent_date"]
        if raw in (None, ""):
            data["quote_sent_date"] = None
        else:
            try:
                data["quote_sent_date"] = date.fromisoformat(str(raw))
            except ValueError:
                errors["quote_sent_date"] = "Pick a valid date"

    _parse_date_field(payload, data, errors, "work_order_date")
    _parse_date_field(payload, data, errors, "advance_date")
    _parse_amount_field(payload, data, errors, "advance_amount")

    if "client_id" in payload:
        raw = payload["client_id"]
        if raw in (None, ""):
            data["client_id"] = None
        else:
            client = None
            try:
                client = visible_clients().filter(Client.id == int(raw)).first()
            except (TypeError, ValueError):
                pass
            if client is None:
                errors["client_id"] = "Choose a client from the list"
            else:
                data["client_id"] = client.id

    if "enquired_by_id" in payload:
        raw = payload["enquired_by_id"]
        if raw in (None, ""):
            data["enquired_by_id"] = None
        else:
            worker = None
            if str(raw).isdigit():
                worker = Worker.query.filter_by(id=int(raw), category="staff").first()
            if worker is None:
                errors["enquired_by_id"] = "Choose someone from the staff list"
            else:
                data["enquired_by_id"] = worker.id

    if "service_ids" in payload:
        raw = payload["service_ids"]
        ids = None
        if isinstance(raw, list):
            try:
                ids = [int(x) for x in raw]
            except (TypeError, ValueError):
                ids = None
        if ids is None:
            errors["service_ids"] = "Choose at least one service"
        else:
            found = Service.query.filter(Service.id.in_(ids)).count() if ids else 0
            if found != len(set(ids)):
                errors["service_ids"] = "Choose valid services"
            else:
                data["service_ids"] = ids

    if "stage" in payload:
        if payload["stage"] in STAGES:
            data["stage"] = payload["stage"]
        else:
            errors["stage"] = "Choose one of the stages"

    return data, errors


def _own_lead_or_404(lead_id: int) -> Lead:
    lead = db.get_or_404(Lead, lead_id)
    if not g.user.is_admin and lead.owner_code != g.user.code:
        abort(404)
    return lead


def _fmt_date(d):
    return d.strftime("%d %b %Y") if d else None


def _log(lead: Lead, kind: str, text: str) -> None:
    lead.activities.insert(0, Activity(kind=kind, text=text))


def _stage_gate_error(lead: Lead, new_stage: str):
    """Why the pipeline refuses this jump, or None if it's fine - each stage needs the one before it
    actually done, not just skipped past."""
    if new_stage == "Quote sent" and not (lead.survey and lead.survey.survey_date):
        return "Complete the site survey first"
    if new_stage == "Negotiation" and not lead.quote_sent_date:
        return "Send a quote first"
    if new_stage == "Work order & advance" and not any(n.finalized for n in lead.negotiations):
        return "Finalize a negotiation round first"
    if new_stage == WON and not (lead.work_order_no and lead.work_order_date and lead.advance_amount is not None and lead.advance_date):
        return "Enter the work order and advance details first"
    return None


def _apply(lead: Lead, data: dict) -> None:
    new_stage = data.pop("stage", None)
    service_ids = data.pop("service_ids", None)

    if new_stage and new_stage != lead.stage:
        # Winning is the one stage move that maps the lead to a client - reused from an existing one, or
        # a brand-new one created for it - so it's the admin's call, not whoever owns the lead.
        if new_stage == WON and not g.user.is_admin:
            abort(403, "Only the admin can mark a lead won.")
        gate_error = _stage_gate_error(lead, new_stage)
        if gate_error:
            abort(422, gate_error)

    # Entering quote details, or the work order and advance, is itself a stage-advancing action, so it
    # needs the same gate as an explicit stage jump would - otherwise a lead could pick those up while
    # still sitting at an earlier stage, before what they depend on exists.
    if data.get("quote_sent_date") and not (lead.survey and lead.survey.survey_date):
        abort(422, "Complete the site survey first")
    if data.get("work_order_no") and not any(n.finalized for n in lead.negotiations):
        abort(422, "Finalize a negotiation round first")

    if "follow_up_date" in data and data["follow_up_date"] != lead.follow_up_date:
        new_date = data["follow_up_date"]
        _log(lead, "followup", f"Follow-up set for {_fmt_date(new_date)}" if new_date else "Follow-up cleared")

    # A quote being sent for the first time, while sitting at Site survey, completes that stage's own
    # step - it moves the lead on to Quote sent, never further. Negotiation only starts once a round is
    # actually logged (see add_negotiation below), and Work order & advance only once its own fields are
    # entered here - no stage gets skipped past.
    quote_just_sent = bool(data.get("quote_sent_date")) and not lead.quote_sent_date
    wo_just_set = bool(data.get("work_order_no")) and not lead.work_order_no

    for field, value in data.items():
        setattr(lead, field, value)

    if service_ids is not None:
        lead.services = Service.query.filter(Service.id.in_(service_ids)).all() if service_ids else []

    if new_stage and new_stage != lead.stage:
        _log(lead, "stage", f"Stage changed: {lead.stage} \u2192 {new_stage}")
        lead.stage = new_stage
        lead.closed_at = utcnow() if new_stage in CLOSED_STAGES else None
        if new_stage == WON and lead.project is None:
            try:
                create_project_from_lead(lead, g.user)
            except ProjectError as err:
                abort(err.status, err.message)
    elif quote_just_sent and lead.stage == "Site survey":
        _log(lead, "stage", f"Stage changed: {lead.stage} \u2192 Quote sent")
        lead.stage = "Quote sent"
    elif wo_just_set and lead.stage == "Negotiation":
        _log(lead, "stage", f"Stage changed: {lead.stage} \u2192 Work order & advance")
        lead.stage = "Work order & advance"


def _needs_name(lead_values: dict, has_client: bool) -> dict:
    if has_client:
        return {}
    if not (lead_values.get("company") or lead_values.get("contact_name")):
        return {"company": "Enter a company or a contact name"}
    return {}


def compute_summary(leads, today: date) -> dict:
    open_leads = [l for l in leads if l.stage in OPEN_STAGES]
    won = [l for l in leads if l.stage == WON]
    lost = [l for l in leads if l.stage == LOST]

    due = [l for l in open_leads if l.follow_up_date and l.follow_up_date <= today]
    overdue = [l for l in due if l.follow_up_date < today]

    def closed_this_month(l):
        if not l.closed_at:
            return False
        local = to_local(l.closed_at)
        return (local.year, local.month) == (today.year, today.month)

    won_month = [l for l in won if closed_this_month(l)]
    closed_total = len(won) + len(lost)

    return {
        "open_count": len(open_leads),
        "open_value": float(sum((l.est_value or 0) for l in open_leads)),
        "due_count": len(due),
        "overdue_count": len(overdue),
        "won_month_count": len(won_month),
        "won_month_value": float(sum((l.est_value or 0) for l in won_month)),
        "win_rate": round(100 * len(won) / closed_total) if closed_total else None,
    }


@bp.get("/state")
def state():
    leads = visible_leads().order_by(Lead.created_at.desc(), Lead.id.desc()).all()
    today = today_local()
    return jsonify(
        me={
            "userid": g.user.userid, "name": g.user.name, "is_admin": g.user.is_admin,
            "modules": [m.key for m in modules_for(g.user)],
        },
        today=today.isoformat(),
        stages=STAGES,
        open_stages=OPEN_STAGES,
        settings=settings_for_client(),
        service_options=[{"id": s.id, "name": s.name} for s in Service.query.filter_by(is_active=True).order_by(Service.sort_order, Service.name)],
        staff=[{"id": w.id, "name": w.name} for w in Worker.query.filter_by(category="staff").order_by(Worker.name)],
        clients=[{"id": c.id, "name": c.name} for c in visible_clients().order_by(Client.name)],
        leads=[l.to_dict() for l in leads],
        summary=compute_summary(leads, today),
    )


def _fetch_pincode(pin: str):
    """Ask India Post's public pincode service. Returns a dict, or None if the pincode does not exist."""
    req = Request(PINCODE_SERVICE + pin, headers={"User-Agent": "lead-desk"})
    with urlopen(req, timeout=6) as res:
        payload = json.load(res)
    entry = payload[0] if payload else {}
    offices = entry.get("PostOffice") or []
    if entry.get("Status") != "Success" or not offices:
        return None
    block = next((o["Block"] for o in offices if o.get("Block") and o["Block"] != "NA"), None)
    return {"state": offices[0]["State"], "district": offices[0]["District"], "city": block or offices[0]["Name"]}


@bp.get("/pincode/<pin>")
def pincode_lookup(pin):
    if not PINCODE_RE.fullmatch(pin):
        abort(400, "Enter a 6-digit pincode")
    row = db.session.get(Pincode, pin)
    if row is None:
        try:
            found = _fetch_pincode(pin)
        except (OSError, ValueError, KeyError, IndexError):
            abort(502, "Could not reach the pincode service. Enter the details yourself.")
        if found is None:
            abort(404, "We could not find that pincode. Enter the details yourself.")
        row = Pincode(pincode=pin, **found)
        db.session.add(row)
        db.session.commit()
    return jsonify(state=row.state, district=row.district, city=row.city)


@bp.post("/leads")
def create_lead():
    data, errors = _validate(_payload())
    data.pop("client_id", None)   # every new lead is unlinked to any client - mapped to one only at Won
    errors.update(_needs_name(data, has_client=False))
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    service_ids = data.pop("service_ids", None)
    lead = Lead(**{k: v for k, v in data.items() if k != "stage"})
    lead.owner_code = g.user.code
    if service_ids:
        lead.services = Service.query.filter(Service.id.in_(service_ids)).all()
    stage = data.get("stage", STAGES[0])
    lead.stage = stage
    if stage in CLOSED_STAGES:
        lead.closed_at = utcnow()
    db.session.add(lead)
    _log(lead, "created", "Lead created")
    db.session.commit()
    return jsonify(lead.to_dict(with_activities=True)), 201


@bp.get("/leads/<int:lead_id>")
def get_lead(lead_id):
    lead = _own_lead_or_404(lead_id)
    return jsonify(lead.to_dict(with_activities=True))


@bp.patch("/leads/<int:lead_id>")
def update_lead(lead_id):
    lead = _own_lead_or_404(lead_id)
    data, errors = _validate(_payload())

    merged = {"company": lead.company, "contact_name": lead.contact_name, **data}
    has_client = (data["client_id"] if "client_id" in data else lead.client_id) is not None
    errors.update(_needs_name(merged, has_client))
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    _apply(lead, data)
    db.session.commit()
    return jsonify(lead.to_dict(with_activities=True))


@bp.delete("/leads/<int:lead_id>")
def delete_lead(lead_id):
    lead = _own_lead_or_404(lead_id)
    db.session.delete(lead)
    db.session.commit()
    return "", 204


@bp.post("/leads/<int:lead_id>/project")
def create_project(lead_id):
    lead = _own_lead_or_404(lead_id)
    try:
        project, reused = create_project_from_lead(lead, g.user)
    except ProjectError as err:
        abort(err.status, err.message)
    db.session.commit()
    return jsonify(project_id=project.id, code=project.code, client_id=project.client_id, client_reused=reused), 201


# ---------- site survey ----------

@bp.put("/leads/<int:lead_id>/survey")
def upsert_survey(lead_id):
    lead = _own_lead_or_404(lead_id)
    payload = _payload()
    errors = {}

    survey_date = None
    raw_date = payload.get("survey_date")
    if raw_date:
        try:
            survey_date = date.fromisoformat(str(raw_date))
        except ValueError:
            errors["survey_date"] = "Pick a valid date"

    surveyor_id = None
    raw_surveyor = payload.get("surveyor_id")
    if raw_surveyor not in (None, ""):
        surveyor = None
        if str(raw_surveyor).isdigit():
            surveyor = Worker.query.filter_by(id=int(raw_surveyor), category="staff").first()
        if surveyor is None:
            errors["surveyor_id"] = "Choose someone from the staff list"
        else:
            surveyor_id = surveyor.id

    site_pincode = str(payload.get("site_pincode") or "").strip()[:6]
    if site_pincode and not PINCODE_RE.fullmatch(site_pincode):
        errors["site_pincode"] = "Enter a 6-digit pincode"

    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    survey = lead.survey or LeadSurvey(lead=lead)
    survey.survey_date = survey_date
    survey.surveyor_id = surveyor_id
    survey.rep_name = str(payload.get("rep_name") or "").strip()[:120]
    survey.rep_role = str(payload.get("rep_role") or "").strip()[:60]
    survey.rep_phone = str(payload.get("rep_phone") or "").strip()[:40]
    survey.site_category = str(payload.get("site_category") or "").strip()[:60]
    survey.site_pincode = site_pincode
    survey.site_state = str(payload.get("site_state") or "").strip()[:80]
    survey.site_district = str(payload.get("site_district") or "").strip()[:80]
    survey.site_city = str(payload.get("site_city") or "").strip()[:120]
    survey.site_address = str(payload.get("site_address") or "").strip()[:400]
    db.session.add(survey)

    # A completed survey while the lead is still sitting at New enquiry moves it along automatically -
    # never backwards, so editing survey details again later doesn't undo later stage progress.
    if survey_date and lead.stage == "New enquiry":
        _log(lead, "stage", f"Stage changed: {lead.stage} → Site survey")
        lead.stage = "Site survey"

    lead.updated_at = utcnow()
    db.session.commit()
    return jsonify(lead.to_dict(with_activities=True))


@bp.post("/leads/<int:lead_id>/survey/photos")
def upload_survey_photos(lead_id):
    lead = _own_lead_or_404(lead_id)
    if lead.survey is None:
        abort(422, "Save the site survey details first")
    files = request.files.getlist("photos")
    if not files:
        abort(422, "Choose at least one photo")
    for f in files:
        try:
            filename = save_upload(f, "survey")
        except UploadError as err:
            abort(422, err.message)
        lead.survey.photos.append(SurveyPhoto(filename=filename))
    lead.updated_at = utcnow()
    db.session.commit()
    return jsonify(lead.to_dict(with_activities=True)), 201


@bp.delete("/leads/<int:lead_id>/survey/photos/<int:photo_id>")
def delete_survey_photo(lead_id, photo_id):
    lead = _own_lead_or_404(lead_id)
    photo = next((p for p in (lead.survey.photos if lead.survey else [])if p.id == photo_id), None)
    if photo is None:
        abort(404)
    delete_upload("survey", photo.filename)
    lead.survey.photos.remove(photo)
    lead.updated_at = utcnow()
    db.session.commit()
    return jsonify(lead.to_dict(with_activities=True))


# ---------- negotiation rounds ----------

def _negotiation_fields(payload, errors):
    date_val = None
    raw_date = payload.get("date")
    if raw_date:
        try:
            date_val = date.fromisoformat(str(raw_date))
        except ValueError:
            errors["date"] = "Pick a valid date"

    estimate = None
    raw_estimate = payload.get("estimate")
    if raw_estimate not in (None, ""):
        try:
            amount = Decimal(str(raw_estimate))
            if not amount.is_finite() or amount < 0 or amount > MAX_VALUE:
                raise InvalidOperation
            estimate = amount.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            errors["estimate"] = "Enter a number, 0 or more"

    authorized_person = str(payload.get("authorized_person") or "").strip()[:120]
    finalized = bool(payload.get("finalized"))
    return date_val, authorized_person, estimate, finalized


@bp.post("/leads/<int:lead_id>/negotiations")
def add_negotiation(lead_id):
    lead = _own_lead_or_404(lead_id)
    if not lead.quote_sent_date:
        abort(422, "Send a quote first")
    # A finalized round settles the deal - it has to be unticked before negotiation can reopen.
    if any(n.finalized for n in lead.negotiations):
        abort(422, "A round is already finalized - untick it to add another round")
    errors = {}
    date_val, authorized_person, estimate, finalized = _negotiation_fields(_payload(), errors)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    round_no = max((n.round_no for n in lead.negotiations), default=0) + 1
    db.session.add(LeadNegotiation(
        lead=lead, round_no=round_no, date=date_val, authorized_person=authorized_person,
        estimate=estimate, finalized=finalized,
    ))
    if lead.stage == "Quote sent":
        _log(lead, "stage", f"Stage changed: {lead.stage} → Negotiation")
        lead.stage = "Negotiation"
    lead.updated_at = utcnow()
    db.session.commit()
    return jsonify(lead.to_dict(with_activities=True)), 201


@bp.patch("/leads/<int:lead_id>/negotiations/<int:round_id>")
def update_negotiation(lead_id, round_id):
    lead = _own_lead_or_404(lead_id)
    round_ = next((n for n in lead.negotiations if n.id == round_id), None)
    if round_ is None:
        abort(404)
    errors = {}
    date_val, authorized_person, estimate, finalized = _negotiation_fields(_payload(), errors)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    round_.date, round_.authorized_person, round_.estimate, round_.finalized = date_val, authorized_person, estimate, finalized
    lead.updated_at = utcnow()
    db.session.commit()
    return jsonify(lead.to_dict(with_activities=True))


@bp.post("/leads/<int:lead_id>/notes")
def add_note(lead_id):
    lead = _own_lead_or_404(lead_id)
    payload = _payload()
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Write a note first", fields={"text": "Write a note first"}), 422
    if len(text) > 2000:
        return jsonify(error="Keep notes under 2000 characters", fields={"text": "Too long"}), 422
    _log(lead, "note", text.strip())
    lead.updated_at = utcnow()
    db.session.commit()
    return jsonify(lead.to_dict(with_activities=True)), 201

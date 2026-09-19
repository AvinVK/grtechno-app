from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import HTTPException, abort

from .constants import CLOSED_STAGES, LOST, OPEN_STAGES, STAGES, WON
from .extensions import db
from .models import Activity, Lead, settings_for_client, utcnow
from .timeutil import to_local, today_local

bp = Blueprint("api", __name__, url_prefix="/api")

TEXT_LIMITS = {
    "contact_name": 120,
    "company": 160,
    "phone": 40,
    "email": 160,
    "site_address": 400,
    "service": 120,
    "source": 120,
    "notes": 5000,
}
MAX_VALUE = Decimal("99999999999")


@bp.errorhandler(HTTPException)
def json_error(err):
    return jsonify(error=err.description or err.name), err.code


def _payload() -> dict:
    # Requiring JSON also blocks cross-site form posts (they cannot send this content type).
    if not request.is_json:
        abort(415, "Send JSON")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "Send a JSON object")
    return data


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

    if "stage" in payload:
        if payload["stage"] in STAGES:
            data["stage"] = payload["stage"]
        else:
            errors["stage"] = "Choose one of the stages"

    return data, errors


def _fmt_date(d):
    return d.strftime("%d %b %Y") if d else None


def _log(lead: Lead, kind: str, text: str) -> None:
    lead.activities.insert(0, Activity(kind=kind, text=text))


def _apply(lead: Lead, data: dict) -> None:
    new_stage = data.pop("stage", None)

    if "follow_up_date" in data and data["follow_up_date"] != lead.follow_up_date:
        new_date = data["follow_up_date"]
        _log(lead, "followup", f"Follow-up set for {_fmt_date(new_date)}" if new_date else "Follow-up cleared")

    for field, value in data.items():
        setattr(lead, field, value)

    if new_stage and new_stage != lead.stage:
        _log(lead, "stage", f"Stage changed: {lead.stage} \u2192 {new_stage}")
        lead.stage = new_stage
        lead.closed_at = utcnow() if new_stage in CLOSED_STAGES else None


def _needs_name(lead_values: dict) -> dict:
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
    leads = Lead.query.order_by(Lead.created_at.desc(), Lead.id.desc()).all()
    today = today_local()
    return jsonify(
        today=today.isoformat(),
        stages=STAGES,
        open_stages=OPEN_STAGES,
        settings=settings_for_client(),
        leads=[l.to_dict() for l in leads],
        summary=compute_summary(leads, today),
    )


@bp.post("/leads")
def create_lead():
    data, errors = _validate(_payload())
    errors.update(_needs_name(data))
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    lead = Lead(**{k: v for k, v in data.items() if k != "stage"})
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
    lead = db.get_or_404(Lead, lead_id)
    return jsonify(lead.to_dict(with_activities=True))


@bp.patch("/leads/<int:lead_id>")
def update_lead(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    data, errors = _validate(_payload())

    merged = {"company": lead.company, "contact_name": lead.contact_name, **data}
    errors.update(_needs_name(merged))
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422

    _apply(lead, data)
    db.session.commit()
    return jsonify(lead.to_dict(with_activities=True))


@bp.delete("/leads/<int:lead_id>")
def delete_lead(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    db.session.delete(lead)
    db.session.commit()
    return "", 204


@bp.post("/leads/<int:lead_id>/notes")
def add_note(lead_id):
    lead = db.get_or_404(Lead, lead_id)
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

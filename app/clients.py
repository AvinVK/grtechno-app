"""Clients (the Client Management service): the customers work is done for."""

import re
from decimal import Decimal

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import abort

from . import categories
from .auth import create_user, visible_clients, visible_projects
from .extensions import db
from .models import Client, Lead, Project, settings_for_client
from .projects import brought_by
from .modules import check_module, has_module
from .timeutil import months_back, today_local
from .validation import Fields, api_errors

bp = Blueprint("clients", __name__)
api_errors(bp)

PINCODE_RE = re.compile(r"[1-9][0-9]{5}")


def _phone_userid(phone: str) -> str:
    """The client's own mobile number, as a login id - strips everything but digits and drops a leading
    country/trunk code (+91, 0...) if the client's phone field has one, down to the last 10 digits (kohal,
    2026-10-23: "the login of client should be mapped to its mobile number... no client will be patient
    enough to enter the code and set the pin. so number will be the mapping key"). Empty if what's left
    isn't a plausible 10-digit mobile number."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) > 10:
        digits = digits[-10:]
    return digits if len(digits) == 10 else ""


@bp.before_request
def _clients_service():
    check_module("clients")


def _client_or_404(client_id: int) -> Client:
    client = visible_clients().filter(Client.id == client_id).first()
    if client is None:
        abort(404)
    return client


def _fields(payload):
    f = Fields(payload)
    f.text("name", 160, required=True, label="the client's name")
    f.text("contact_name", 120)
    f.text("phone", 40)
    f.text("email", 160)
    f.text("site_name", 160)
    f.text("site_category", 60)
    f.text("pincode", 6)
    f.text("state", 80)
    f.text("district", 80)
    f.text("city", 120)
    f.text("address", 400)
    f.text("notes", 5000)
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
    return [
        {
            "id": p.id, "code": p.code, "title": p.title, "status": p.status, "services": p.service_names,
            "estimated_amount": float(p.estimated_amount) if p.estimated_amount is not None else None,
            "net_amount": float(p.net_amount) if p.net_amount is not None else None,
        }
        for p in rows
    ]


# ---------- Client tally (kohal, 2026-11-05) ----------
#
# "The way i see supplier tally, i wanna see client tally ... for each client whats the total worth of the client, how much is
# paid and how much is left." Per client: worth is what their projects are worth (each project's own net amount - the final
# amount once it is in, else the estimate less any discount), paid is what has actually been received on them (the payment
# steps with a date of payment), and left is the difference. Computed from the live records, never stored. Scoped like the
# Clients list: only the clients this person may see, and only the projects they may see.

def _tally_for(client, projects):
    worth = sum((p.net_amount for p in projects if p.net_amount is not None), Decimal("0"))
    paid = sum((p.paid_amount for p in projects), Decimal("0"))
    return {"id": client.id, "name": client.name, "contact_name": client.contact_name, "city": client.city,
            "projects": len(projects), "worth": float(worth), "paid": float(paid), "left": float(worth - paid)}


def _tally_projects(client):
    return visible_projects().filter(Project.client_id == client.id).order_by(Project.id.desc()).all()


@bp.get("/client-analysis")
def analysis_page():
    return render_template("client_analysis.html")


@bp.get("/client-tally")
def tally_page():
    # The tally is the second subtab of Client analysis now; the old address still works for anyone who saved it.
    return redirect(url_for("clients.analysis_page") + "#tally")


@bp.get("/api/clients/tally")
def client_tally():
    clients = visible_clients().filter(Client.is_adhoc.is_(False)).order_by(Client.name).all()
    rows = [_tally_for(c, _tally_projects(c)) for c in clients]
    rows.sort(key=lambda r: (-r["left"], r["name"].lower()))
    return jsonify(clients=rows, totals={k: round(sum(r[k] for r in rows), 2) for k in ("worth", "paid", "left")},
                   can_open_projects=has_module(g.user, "projects"), currency=settings_for_client()["currency"])


# ---------- Client analysis (kohal, 2026-11-05: "client rename to client analysis and have 2 subtabs, analysis and tally") ----------
#
# The Analysis subtab: charts over the same clients and projects the tally covers (never adhoc customers). Worth and paid are worked out
# exactly as in the tally; money received per month is the payment steps by the day they were received.

PROJECT_STATUS = {"planned": "Planned", "running": "Running", "on_hold": "On hold", "final_estimate_sent": "Final estimate sent",
                  "completed": "Completed"}
RECEIVED_RANGES = {"3": "Last 3 months", "6": "Last 6 months", "12": "Last 12 months"}
MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@bp.get("/api/clients/analysis")
def client_analysis():
    span = request.args.get("range") or "12"
    if span not in RECEIVED_RANGES:
        abort(422, "Pick a valid range")
    today = today_local()
    clients = visible_clients().filter(Client.is_adhoc.is_(False)).order_by(Client.name).all()
    projects_of = {c.id: _tally_projects(c) for c in clients}
    rows = [_tally_for(c, projects_of[c.id]) for c in clients]
    worth_rows = sorted((r for r in rows if r["worth"] > 0), key=lambda r: (-r["worth"], r["name"].lower()))

    by_status = {}
    for projects in projects_of.values():
        for p in projects:
            row = by_status.setdefault(p.status, {"status": p.status, "label": PROJECT_STATUS.get(p.status, p.status), "projects": 0, "worth": 0.0})
            row["projects"] += 1
            row["worth"] += float(p.net_amount) if p.net_amount is not None else 0.0

    n = int(span)
    first = months_back(today, n - 1)
    received = {}
    for projects in projects_of.values():
        for p in projects:
            for x in p.payments:
                if x.paid_date is not None and x.paid_date >= first:
                    received[(x.paid_date.year, x.paid_date.month)] = received.get((x.paid_date.year, x.paid_date.month), 0.0) + float(x.amount)
    points = []
    for i in range(n):
        m = months_back(today, n - 1 - i)
        points.append({"key": f"{m.year}-{m.month:02d}", "label": f"{MONTH_ABBR[m.month]} {str(m.year)[2:]}",
                       "count": round(received.get((m.year, m.month), 0.0), 2)})

    return jsonify(
        totals={k: round(sum(r[k] for r in rows), 2) for k in ("worth", "paid", "left")}, clients=len(rows),
        top_clients=worth_rows, status=sorted(by_status.values(), key=lambda r: (-r["worth"], r["label"])),
        received={"range": span, "label": RECEIVED_RANGES[span], "unit": "month", "points": points, "total": round(sum(p["count"] for p in points), 2)},
        ranges=[{"value": k, "label": v} for k, v in RECEIVED_RANGES.items()], currency=settings_for_client()["currency"])


@bp.get("/api/clients/<int:client_id>/tally")
def client_tally_detail(client_id):
    client = _client_or_404(client_id)
    projects = _tally_projects(client)
    return jsonify(
        client=_tally_for(client, projects),
        projects=[{"id": p.id, "code": p.code, "title": p.title, "status": p.status,
                   "worth": float(p.net_amount) if p.net_amount is not None else None, "paid": float(p.paid_amount),
                   "left": float(p.net_amount - p.paid_amount) if p.net_amount is not None else None,
                   # the project's payment schedule, for the slide-up on the tally (read only)
                   "payments": [x.to_dict() for x in p.payments]} for p in projects],
        can_open_projects=has_module(g.user, "projects"), currency=settings_for_client()["currency"])


@bp.get("/clients")
def page():
    title = "Clients" if g.user.sees_all else "My clients"
    return render_template("clients.html", page_title=title)


@bp.get("/api/clients")
def list_clients():
    # Adhoc customers are not clients (kohal, 2026-10-31: "this adhoc thing wont be a client, it will be adhoc
    # project") - they live on their project, so they stay out of the Clients list.
    clients = visible_clients().filter(Client.is_adhoc.is_(False)).order_by(Client.name).all()
    settings = settings_for_client()
    return jsonify(clients=[c.to_dict() for c in clients], site_categories=settings["site_categories"], currency=settings["currency"])


@bp.get("/api/clients/<int:client_id>")
def get_client(client_id):
    client = _client_or_404(client_id)
    settings = settings_for_client()
    # Who brought the client in: whoever brought their first project from a lead, else whoever added them.
    first_from_lead = min((p for p in client.projects if p.lead is not None), key=lambda p: p.id, default=None)
    login = client.logins[0] if client.logins else None
    return jsonify(
        client=client.to_dict(), projects=_project_rows(client), is_admin=g.user.is_admin,
        site_categories=settings["site_categories"], currency=settings["currency"],
        brought_by=brought_by(first_from_lead.lead if first_from_lead else None, client.owner),
        # Whether this client already has their own sign-in (kohal, 2026-10-22: "clients should be able to
        # login") - give_login below either creates one or, once this is set, re-issues a fresh setup code
        # on the same login rather than creating a second.
        login={"userid": login.userid, "status": login.status} if login else None,
    )


@bp.post("/api/clients/<int:client_id>/login")
def give_login(client_id):
    """Set this client up with their own sign-in (or return the one they already have) - admin only. The
    one place a User gets linked to a Client (User.client_id) - see auth.visible_projects' own "client"
    branch for what that then scopes them to see.

    The userid is the client's own phone number, and that is the whole sign-in: no setup code, no PIN
    (kohal, 2026-10-26: "no need for setup code as well... that client just needs to enter the contact and
    see the projects") - see auth.login's client branch. Safe to tap again: it just returns the same login
    so the admin can share the link once more."""
    if not g.user.is_admin:
        abort(403, "Only the admin can give a client login access.")
    client = _client_or_404(client_id)
    user = client.logins[0] if client.logins else None
    if user is None:
        phone_userid = _phone_userid(client.phone)
        if not phone_userid:
            return jsonify(error="Add a valid 10-digit phone number for this client first."), 422
        try:
            user, _ = create_user(client.contact_name or client.name, role="client", userid=phone_userid)
        except ValueError as err:
            return jsonify(error=str(err)), 422
        user.client_id = client.id
        user.setup_code_hash = None       # a phone-only login never uses the one-time code create_user made
        user.setup_code_expires = None
        db.session.add(user)
    db.session.commit()
    return jsonify(user={"code": user.code, "userid": user.userid, "name": user.name}), 201


@bp.patch("/api/clients/<int:client_id>")
def update_client(client_id):
    client = _client_or_404(client_id)
    f = _fields(_payload())
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    for key, value in f.data.items():
        setattr(client, key, value)
    categories.note_request(f.data.get("site_category"), g.user.code)
    db.session.commit()
    return jsonify(client=client.to_dict(), projects=_project_rows(client))


@bp.post("/api/clients")
def create_client():
    """Add a client directly - for work done before the app, or a client who never came in as a lead."""
    f = _fields(_payload())
    if not f.data.get("name") and "name" not in f.errors:
        f.errors["name"] = "Enter the client's name"
    if f.errors:
        return jsonify(error="Check the highlighted fields", fields=f.errors), 422
    client = Client(owner_code=g.user.code, **f.data)
    db.session.add(client)
    categories.note_request(f.data.get("site_category"), g.user.code)
    db.session.commit()
    return jsonify(client=client.to_dict()), 201


@bp.delete("/api/clients/<int:client_id>")
def delete_client(client_id):
    """TEMPORARY - removes duplicate or wrongly added clients while the old records are being cleaned up.
    Remove this route and its button once that's done. Refuses while the client still has projects; the
    leads that pointed at it stay, just without a client."""
    if not g.user.is_admin:
        abort(403, "Only the admin can delete a client.")
    client = _client_or_404(client_id)
    if client.projects:
        abort(422, "This client still has projects - delete those first.")
    Lead.query.filter_by(client_id=client.id).update({"client_id": None})
    db.session.delete(client)
    db.session.commit()
    return "", 204

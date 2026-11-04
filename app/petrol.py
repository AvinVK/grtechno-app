"""Petrol payment (kohal, 2026-10-27: "same as fooding, we need option of petrol payment") - an employee who
rides their own vehicle to site is paid by the kilometre (constants.PETROL_RATE_PER_KM) for the distance
between the odometer reading at check-in and at check-out.

Switched on per employee with Employee management's "Petrol payment?" toggle (Worker.petrol_enabled). While
on, app/attendance.py refuses a check-in or check-out that doesn't come with an odometer reading (a whole
number) and a photo of the odometer - enforced there, not only by the screen. Each session's pair is one
PetrolEntry, approved once by the admin or the project manager of that session's project (can_approve_petrol)
- the amount only counts once approved. Once an entry has been decided and a day has passed, its two photos
are deleted to keep the database light (purge_old_photos, run lazily - PythonAnywhere's free plan has no
scheduled jobs, see app/deploy.py); the readings, kilometres and amount stay as the register.

Two audiences share /petrol, same split as /fooding: the admin or accountant sees everyone on petrol payment
and taps a person for their register; an employee on petrol payment sees their own register. Approving is
done from the Me hub's "Pending approvals" (me.js), where the admin and project managers already approve
attendance."""

from decimal import Decimal

from flask import Blueprint, abort, g, jsonify, render_template, request

from .auth import PROJECT_MANAGER_ROLE_KEYS, can_manage_fooding, visible_projects
from .constants import PETROL_RATE_PER_KM
from .fooding import PAYMENT_MODES
from .extensions import db
from .models import PetrolEntry, PetrolPayout, Project, Worker, settings_for_client, utcnow
from .timeutil import today_local
from .uploads import IMAGE_TYPES, UploadError, delete_upload, save_upload
from .validation import api_errors, parse_money

bp = Blueprint("petrol", __name__)
api_errors(bp)

MAX_READING = 9_999_999       # an odometer shows at most 7 digits on anything we would see


def petrol_on(user) -> bool:
    """Whether this signed-in person is on petrol payment (Worker.petrol_enabled)."""
    worker = Worker.query.filter_by(user_code=user.code).first()
    return bool(worker and worker.petrol_enabled)


def parse_reading(raw, errors: dict, key: str):
    """A whole-number odometer reading from a form or JSON value. Adds to `errors` and returns None if it
    isn't one."""
    text = str(raw if raw is not None else "").strip()
    if not text.isdigit() or int(text) > MAX_READING:
        errors[key] = "Enter the odometer reading as a whole number"
        return None
    return int(text)


def odometer_file(files, key: str, errors: dict):
    """The odometer photo that came with the request, if there is one - an error when there isn't, since a
    photo is mandatory while petrol payment is on. Nothing is saved here; see save_odometer."""
    file = files.get(key)
    if file is None or not file.filename:
        errors[key] = "Take a photo of the odometer"
        return None
    if (file.mimetype or "").lower() not in IMAGE_TYPES:
        errors[key] = "The odometer photo must be a JPEG, PNG or WEBP image"
        return None
    return file


def save_odometer(file) -> str:
    try:
        return save_upload(file, "odometer")
    except UploadError as err:
        abort(422, err.message)


def can_approve_petrol(user, project) -> bool:
    """The admin or Company Director, or a project manager of that session's project (on a project they can
    actually see - the same narrowing as attendance approval). Sessions with no project (office or marketing
    work) are the admin's or Company Director's alone."""
    if user.is_admin or user.role_key == "company_director":
        return True
    if project is None or user.role_key not in PROJECT_MANAGER_ROLE_KEYS:
        return False
    return visible_projects(user).filter(Project.id == project.id).first() is not None


def purge_old_photos() -> None:
    """Delete the odometer photos of every entry that has been approved or rejected and is from before today
    (kohal: "next day, you can delete that pic so that the backend db does not get heavier"). A photo still
    waiting for a decision is kept until someone decides - nothing is lost before review."""
    rows = (PetrolEntry.query
            .filter(PetrolEntry.work_date < today_local(), PetrolEntry.status != "pending")
            .filter((PetrolEntry.in_photo.isnot(None)) | (PetrolEntry.out_photo.isnot(None)))
            .all())
    for row in rows:
        for name in ("in_photo", "out_photo"):
            if getattr(row, name):
                delete_upload("odometer", getattr(row, name))
                setattr(row, name, None)
    if rows:
        db.session.commit()


def _register(entries, user_code=None):
    """Rows of a register, newest first, plus what has been approved in total and this month - and, with the person's
    code, their petrol balance: what is approved, less everything paid (per-day payments and payouts), what is waiting
    on the admin, and how much more they may still ask for."""
    today = today_local()
    approved = [e for e in entries if e.status == "approved" and e.amount is not None]
    total = sum((e.amount for e in approved), Decimal("0"))
    month = sum((e.amount for e in approved if (e.work_date.year, e.work_date.month) == (today.year, today.month)), Decimal("0"))
    km_month = sum((e.km for e in approved if (e.work_date.year, e.work_date.month) == (today.year, today.month)), 0)
    paid = sum((e.amount for e in approved if e.cash_status == "paid"), Decimal("0"))
    asked = sum((e.amount for e in approved if e.cash_status == "requested"), Decimal("0"))      # asked day by day, before payouts
    payouts = PetrolPayout.query.filter_by(user_code=user_code).order_by(PetrolPayout.requested_at.desc(), PetrolPayout.id.desc()).all() if user_code else []
    paid += sum((o.amount_paid or Decimal("0") for o in payouts if o.status == "paid"), Decimal("0"))
    asked += sum((o.amount for o in payouts if o.status == "requested"), Decimal("0"))
    balance = total - paid
    return {
        "entries": [e.to_dict() for e in entries],
        "approved_total": float(total), "month_total": float(month), "month_km": km_month,
        "paid_total": float(paid), "unpaid_total": float(balance),
        "requested_total": float(asked), "can_request_up_to": float(max(balance - asked, Decimal("0"))),
        "settled": bool(total > 0 and balance <= 0),
        "payouts": [o.to_dict() for o in payouts],
        "rate_per_km": PETROL_RATE_PER_KM, "currency": settings_for_client()["currency"],
    }


def _completed_entries(user_code):
    return (PetrolEntry.query.filter(PetrolEntry.user_code == user_code, PetrolEntry.out_reading.isnot(None))
            .order_by(PetrolEntry.work_date.desc(), PetrolEntry.id.desc()).limit(300).all())


# ---------- the page, same split as /fooding ----------

@bp.get("/petrol")
def page():
    if can_manage_fooding(g.user):
        return render_template("petrol.html", page_title="Petrol", mode="manage")
    if not petrol_on(g.user):
        abort(403, "Petrol payment is only for employees it has been switched on for.")
    return render_template("petrol.html", page_title="Petrol", mode="own")


@bp.get("/api/petrol/me")
def my_petrol():
    if not petrol_on(g.user):
        abort(403, "Petrol payment is only for employees it has been switched on for.")
    purge_old_photos()
    return jsonify(**_register(_completed_entries(g.user.code), g.user.code))


@bp.get("/api/petrol")
def list_petrol():
    if not can_manage_fooding(g.user):
        abort(403, "Only the admin or accountant can see everyone's petrol.")
    purge_old_photos()
    workers = Worker.query.filter(Worker.petrol_enabled.is_(True)).order_by(Worker.name).all()
    rows = []
    for w in workers:
        reg = _register(_completed_entries(w.user_code), w.user_code) if w.user_code else _register([])
        pending = (PetrolEntry.query.filter(PetrolEntry.user_code == w.user_code, PetrolEntry.status == "pending",
                                            PetrolEntry.out_reading.isnot(None)).count() if w.user_code else 0)
        rows.append({"worker_id": w.id, "worker_name": w.name, "month_total": reg["month_total"],
                     "month_km": reg["month_km"], "approved_total": reg["approved_total"], "pending": pending,
                     "unpaid_total": reg["unpaid_total"]})
    return jsonify(workers=rows, rate_per_km=PETROL_RATE_PER_KM, currency=settings_for_client()["currency"],
                   cash_waiting=PetrolEntry.query.filter_by(cash_status="requested").count() + PetrolPayout.query.filter_by(status="requested").count())


@bp.get("/api/petrol/worker/<int:worker_id>")
def worker_register(worker_id):
    if not can_manage_fooding(g.user):
        abort(403, "Only the admin or accountant can see everyone's petrol.")
    worker = db.session.get(Worker, worker_id)
    if worker is None or not worker.petrol_enabled:
        abort(404)
    purge_old_photos()
    return jsonify(worker_name=worker.name, **_register(_completed_entries(worker.user_code) if worker.user_code else [], worker.user_code))


# ---------- cash requests: an approved day's amount, asked for by the employee ----------
# (kohal, 2026-10-30: "after the odo readings are approved, the employee should get a button to request for that
# amount of cash... only admin or accountant should be able to approve it... the approver have to enter the mode
# of payment")

@bp.post("/api/petrol/<int:entry_id>/request-cash")
def request_cash(entry_id):
    entry = db.session.get(PetrolEntry, entry_id)
    if entry is None or entry.user_code != g.user.code:
        abort(404)
    if entry.status != "approved":
        abort(409, "This day hasn't been approved yet.")
    if entry.cash_status in ("requested", "paid"):
        abort(409, "This has already been asked for." if entry.cash_status == "requested" else "This has already been paid.")
    if not entry.amount or entry.amount <= 0:
        abort(409, "There is no amount to ask for.")
    entry.cash_status = "requested"
    entry.cash_requested_at = utcnow()
    entry.cash_decided_by_code = None
    entry.cash_decided_at = None
    entry.cash_mode = ""
    db.session.commit()
    return jsonify(entry=entry.to_dict())


@bp.get("/api/petrol/requests")
def list_cash_requests():
    """Cash requests waiting for the admin or accountant, and the history of those already decided."""
    _manage_only()
    purge_old_photos()
    pending = (PetrolEntry.query.filter_by(cash_status="requested")
               .order_by(PetrolEntry.cash_requested_at).all())
    history = (PetrolEntry.query.filter(PetrolEntry.cash_status.in_(("paid", "rejected")))
               .order_by(db.func.coalesce(PetrolEntry.cash_decided_at, PetrolEntry.created_at).desc(), PetrolEntry.id.desc())
               .limit(200).all())
    rows = []
    for e in pending:
        d = e.to_dict()
        # Who gets paid, for opening a payment app already filled in (kohal, 2026-11-02).
        w = Worker.query.filter_by(user_code=e.user_code).first()
        d["payee"] = {"upi_id": (w.upi_id if w else "") or "", "phone": (w.phone if w else "") or ""}
        rows.append(d)
    payout_rows = []
    for o in PetrolPayout.query.filter_by(status="requested").order_by(PetrolPayout.requested_at).all():
        d = o.to_dict()
        w = Worker.query.filter_by(user_code=o.user_code).first()
        d["payee"] = {"upi_id": (w.upi_id if w else "") or "", "phone": (w.phone if w else "") or ""}
        d["balance"] = _register(_completed_entries(o.user_code), o.user_code)["unpaid_total"]
        payout_rows.append(d)
    payout_history = (PetrolPayout.query.filter(PetrolPayout.status.in_(("paid", "rejected")))
                      .order_by(db.func.coalesce(PetrolPayout.decided_at, PetrolPayout.requested_at).desc(), PetrolPayout.id.desc()).limit(200).all())
    return jsonify(pending=rows, history=[e.to_dict() for e in history], can_decide=g.user.is_admin,
                   payouts=payout_rows, payout_history=[o.to_dict() for o in payout_history],
                   payment_modes=list(PAYMENT_MODES), currency=settings_for_client()["currency"])


@bp.post("/api/petrol/payouts")
def request_payout():
    """The employee's one ask for petrol money (kohal, 2026-11-04) - any amount up to what they are still owed and
    have not already asked for; left blank it is all of it. One waiting at a time."""
    if not petrol_on(g.user):
        abort(403, "Petrol payment is only for employees it has been switched on for.")
    if PetrolPayout.query.filter_by(user_code=g.user.code, status="requested").first() is not None:
        abort(409, "You already have a petrol request waiting on the admin.")
    reg = _register(_completed_entries(g.user.code), g.user.code)
    available = Decimal(str(reg["can_request_up_to"]))
    payload = request.get_json(silent=True) if request.is_json else None
    raw = (payload or {}).get("amount") if isinstance(payload, dict) else None
    errors = {}
    amount = parse_money(raw, errors) if raw not in (None, "") else available
    shown = f"{available:,.2f}".rstrip("0").rstrip(".")
    if not errors:
        if available <= 0:
            errors["amount"] = "There is nothing left to ask for"
        elif amount is None or amount <= 0:
            errors["amount"] = "Enter an amount greater than 0"
        elif amount > available:
            errors["amount"] = f"You can ask for up to {settings_for_client()['currency']}{shown}"
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    db.session.add(PetrolPayout(user_code=g.user.code, amount=amount, status="requested"))
    db.session.commit()
    return jsonify(**_register(_completed_entries(g.user.code), g.user.code)), 201


@bp.post("/api/petrol/payouts/<int:payout_id>/approve")
def approve_payout(payout_id):
    """Pay it - the admin's alone. They say which account it comes from and how much is actually paid (up to what was
    asked, prefilled with all of it); that amount settles against the employee's balance and the rest stays owed."""
    _manage_only()
    _admin_pays()
    payout = db.session.get(PetrolPayout, payout_id)
    if payout is None:
        abort(404)
    if payout.status != "requested":
        abort(409, "This isn't waiting for approval.")
    payload = request.get_json(silent=True) if request.is_json else None
    payload = payload if isinstance(payload, dict) else {}
    errors = {}
    account = payload.get("payment_mode")
    if account not in PAYMENT_MODES:
        errors["payment_mode"] = "Choose the account it is paid from"
    raw = payload.get("amount")
    amount = parse_money(raw, errors) if raw not in (None, "") else payout.amount
    if "amount" not in errors:
        if amount is None or amount <= 0:
            errors["amount"] = "Enter an amount greater than 0"
        elif amount > payout.amount:
            shown = f"{payout.amount:,.2f}".rstrip("0").rstrip(".")
            errors["amount"] = f"Only {settings_for_client()['currency']}{shown} was asked for"
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    payout.status = "paid"
    payout.amount_paid = amount
    payout.payment_account = account
    payout.decided_by_code = g.user.code
    payout.decided_at = utcnow()
    db.session.commit()
    return jsonify(payout=payout.to_dict())


@bp.post("/api/petrol/payouts/<int:payout_id>/reject")
def reject_payout(payout_id):
    _manage_only()
    _admin_pays()
    payout = db.session.get(PetrolPayout, payout_id)
    if payout is None:
        abort(404)
    if payout.status != "requested":
        abort(409, "This isn't waiting for approval.")
    payout.status = "rejected"
    payout.decided_by_code = g.user.code
    payout.decided_at = utcnow()
    db.session.commit()
    return jsonify(payout=payout.to_dict())


def _manage_only():
    if not can_manage_fooding(g.user):
        abort(403, "Only the admin or accountant can handle petrol cash requests.")


def _admin_pays():
    """Approving or rejecting a petrol cash request is paying money out through the bank accounts, so it is the admin's
    alone (kohal, 2026-11-02: "for petrol also do it admin-style"). The accountant can still see the list."""
    if not g.user.is_admin:
        abort(403, "Only the admin can approve or reject petrol cash - it is paid out through the bank accounts.")


@bp.post("/api/petrol/requests/<int:entry_id>/approve")
def approve_cash_request(entry_id):
    """Pay it: the approver says how (Cash or Online/UPI) - required."""
    _manage_only()
    _admin_pays()
    entry = db.session.get(PetrolEntry, entry_id)
    if entry is None:
        abort(404)
    if entry.cash_status != "requested":
        abort(409, "This isn't waiting for approval.")
    payload = request.get_json(silent=True) if request.is_json else None
    mode = (payload or {}).get("payment_mode") if isinstance(payload, dict) else None
    if mode not in PAYMENT_MODES:
        return jsonify(error="Choose how it was paid", fields={"payment_mode": "Choose how it was paid"}), 422
    entry.cash_status = "paid"
    entry.cash_mode = mode
    entry.cash_decided_by_code = g.user.code
    entry.cash_decided_at = utcnow()
    db.session.commit()
    return jsonify(entry=entry.to_dict())


@bp.post("/api/petrol/requests/<int:entry_id>/reject")
def reject_cash_request(entry_id):
    _manage_only()
    _admin_pays()
    entry = db.session.get(PetrolEntry, entry_id)
    if entry is None:
        abort(404)
    if entry.cash_status != "requested":
        abort(409, "This isn't waiting for approval.")
    entry.cash_status = "rejected"
    entry.cash_decided_by_code = g.user.code
    entry.cash_decided_at = utcnow()
    db.session.commit()
    return jsonify(entry=entry.to_dict())


# ---------- approval ----------

@bp.get("/api/petrol/approvals")
def approvals():
    """Finished (checked-out) entries still waiting for a decision that the signed-in person may make."""
    purge_old_photos()
    pending = (PetrolEntry.query.filter(PetrolEntry.status == "pending", PetrolEntry.out_reading.isnot(None))
               .order_by(PetrolEntry.created_at).all())
    return jsonify(approvals=[e.to_dict() for e in pending if can_approve_petrol(g.user, e.attendance.project)],
                   rate_per_km=PETROL_RATE_PER_KM, currency=settings_for_client()["currency"])


def _decide(entry_id, status):
    entry = db.session.get(PetrolEntry, entry_id)
    if entry is None:
        abort(404)
    if entry.status != "pending" or entry.out_reading is None:
        abort(409, "This entry isn't waiting for approval.")
    if not can_approve_petrol(g.user, entry.attendance.project):
        abort(403, "Only the admin or this project's manager can approve this.")
    entry.status = status
    entry.approved_by_code = g.user.code
    entry.approved_at = utcnow()
    db.session.commit()
    return jsonify(entry=entry.to_dict())


@bp.post("/api/petrol/<int:entry_id>/approve")
def approve(entry_id):
    return _decide(entry_id, "approved")


@bp.post("/api/petrol/<int:entry_id>/reject")
def reject(entry_id):
    return _decide(entry_id, "rejected")

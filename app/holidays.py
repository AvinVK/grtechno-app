"""Holidays (kohal, 2026-11-10: "give power to admin to declare a holiday on any particular day. once declared, that day should be a paid
leave for selected employees. because, for eg, eid holiday for one religion and diwali holiday for one religion. this above logic is for
daily wages people. for salaried it will be for all the employees who are salaried. have a subtab in attendance called holidays").

The admin declares a day as a holiday with a name:
  - every salaried employee gets it automatically - the day is a paid day, never an absence;
  - for daily-wage and contractor staff the admin picks who gets it (Eid for some, Diwali for others) - a picked person is paid their
    day's wage for it, as if they had worked (they are paid once if they came in anyway); everyone else is paid for the days worked only.

Payroll (app/payroll.py), the attendance register (app/workers.py) and leave counting (app/leaves.py) read the helpers below. Everyone who
sees the Attendance tabs can look at the list; only the admin declares, changes or removes one."""

from datetime import date, timedelta

from flask import Blueprint, abort, g, jsonify, request

from .extensions import db
from .models import Holiday, HolidayWorker, Worker
from .modules import check_module
from .timeutil import today_local
from .validation import api_errors

HOLIDAY_START = date(2026, 10, 1)          # = app/payroll.py's PAYROLL_START: payroll does not look before it
MAX_AHEAD_DAYS = 366
DAY_RATE_TYPES = ("daily_wages", "contractor")

bp = Blueprint("holidays", __name__)
api_errors(bp)


@bp.before_request
def _attendance_service():
    check_module("attendance")


class HolidayBook:
    """The holidays between two dates, read once - `days(worker)` is the days among them that are paid holidays for that person."""

    def __init__(self, start: date, end: date):
        self.rows = Holiday.query.filter(Holiday.holiday_date >= start, Holiday.holiday_date <= end).all()
        self._picked = {}
        for h in self.rows:
            for link in h.links:
                self._picked.setdefault(link.worker_id, {}).setdefault(h.holiday_date, []).append(h.name)
        self._all = {}
        for h in self.rows:
            self._all.setdefault(h.holiday_date, []).append(h.name)

    def labels(self, worker, start=None, end=None) -> dict:
        """{day: "Name, Name"} for the paid holidays of this person - every holiday for a salaried employee, only the ones they were
        picked for otherwise."""
        base = self._all if worker.employment_type == "regular" else self._picked.get(worker.id, {})
        return {d: ", ".join(names) for d, names in base.items() if (start is None or d >= start) and (end is None or d <= end)}

    def days(self, worker, start=None, end=None) -> set:
        return set(self.labels(worker, start, end))


def holiday_days(worker, start: date, end: date) -> set:
    """The days in [start, end] that are paid holidays for this person."""
    if end < start:
        return set()
    return HolidayBook(start, end).days(worker)


def declared_days(start: date, end: date) -> set:
    """Every day in [start, end] declared a holiday for anyone - what leave counting skips (leave is for salaried staff, who get all)."""
    return {h.holiday_date for h in Holiday.query.filter(Holiday.holiday_date >= start, Holiday.holiday_date <= end)} if end >= start else set()


def holiday_dict(h, today: date, with_workers: bool) -> dict:
    out = {"id": h.id, "date": h.holiday_date.isoformat(), "name": h.name, "upcoming": h.holiday_date >= today,
           "worker_count": len(h.links)}
    if with_workers:
        out["workers"] = sorted(({"id": link.worker.id, "name": link.worker.name} for link in h.links), key=lambda w: w["name"].lower())
    return out


def _own_worker():
    return Worker.query.filter_by(user_code=g.user.code).first()


def _admin_only():
    if not g.user.is_admin:
        abort(403, "Only the admin declares holidays.")


@bp.get("/api/holidays")
def list_holidays():
    today = today_local()
    admin = g.user.is_admin
    rows = Holiday.query.order_by(Holiday.holiday_date.desc(), Holiday.id).limit(300).all()
    mine = None if admin else _own_worker()
    if mine is not None:                                 # someone with their own employee record sees the holidays they get
        rows = [h for h in rows if mine.employment_type == "regular" or any(link.worker_id == mine.id for link in h.links)]
    payload = {"holidays": [holiday_dict(h, today, admin) for h in rows], "can_manage": admin, "today": today.isoformat(),
               "mine": mine is not None}
    if admin:
        payload["employees"] = [{"value": str(w.id), "label": w.name}
                                for w in Worker.query.filter(Worker.employment_type.in_(DAY_RATE_TYPES)).order_by(Worker.name)]
    return jsonify(**payload)


def _fields(payload, errors, current_id=None):
    try:
        day = date.fromisoformat(str(payload.get("date") or ""))
        if day < HOLIDAY_START:
            errors["date"] = "Payroll in the app starts on 1 Oct 2026"
        elif day > today_local() + timedelta(days=MAX_AHEAD_DAYS):
            errors["date"] = "That is too far ahead"
    except ValueError:
        day = None
        errors["date"] = "Pick the day"
    name = str(payload.get("name") or "").strip()
    if not name:
        errors["name"] = "Give the holiday a name"
    elif len(name) > 120:
        errors["name"] = "Keep the name under 120 characters"
    raw = payload.get("worker_ids", [])
    workers = []
    if not isinstance(raw, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in raw):
        errors["worker_ids"] = "Pick employees from the list"
    else:
        for wid in dict.fromkeys(raw):
            w = db.session.get(Worker, wid)
            if w is None or w.employment_type not in DAY_RATE_TYPES:
                errors["worker_ids"] = "Only daily-wage and contractor employees can be picked - salaried employees always get it"
                break
            workers.append(w)
    if day and name and "date" not in errors:
        twin = Holiday.query.filter(Holiday.holiday_date == day, db.func.lower(Holiday.name) == name.lower())
        if current_id is not None:
            twin = twin.filter(Holiday.id != current_id)
        if twin.first() is not None:
            errors["name"] = "That holiday is already declared for this day"
    return day, name, workers


def _holiday_or_404(holiday_id):
    h = db.session.get(Holiday, holiday_id)
    if h is None:
        abort(404, "That holiday is already gone")
    return h


def _payload():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    return payload


@bp.post("/api/holidays")
def declare_holiday():
    _admin_only()
    errors = {}
    day, name, workers = _fields(_payload(), errors)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    h = Holiday(holiday_date=day, name=name, created_by_code=g.user.code)
    h.links = [HolidayWorker(worker_id=w.id) for w in workers]
    db.session.add(h)
    db.session.commit()
    return jsonify(holiday=holiday_dict(h, today_local(), True)), 201


@bp.patch("/api/holidays/<int:holiday_id>")
def change_holiday(holiday_id: int):
    _admin_only()
    h = _holiday_or_404(holiday_id)
    errors = {}
    day, name, workers = _fields(_payload(), errors, current_id=h.id)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    h.holiday_date, h.name = day, name
    h.links = [HolidayWorker(worker_id=w.id) for w in workers]
    db.session.commit()
    return jsonify(holiday=holiday_dict(h, today_local(), True))


@bp.delete("/api/holidays/<int:holiday_id>")
def remove_holiday(holiday_id: int):
    _admin_only()
    db.session.delete(_holiday_or_404(holiday_id))
    db.session.commit()
    return jsonify(ok=True)

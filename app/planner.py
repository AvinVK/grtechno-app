"""The admin's meeting planner and scheduler (kohal, 2026-11-16: "a meeting planner and scheduler (auto and manual scheduler) for admin to plan the
day and meetings for future. this should be in me tab").

Admin only. A day is a list of meetings (the fields of his meeting sheet - date, client name, address, contact no, purpose, place, date and time of
the meeting, remark or feedback, next schedule plan) and simple to-do tasks. Two ways to give them a time:
  - manually: pick the time on the meeting or task;
  - automatically ("it should schedule based on the plan already entered by the admin"): the auto scheduler places whatever has no time yet into the
    first free slot of its day, around the times already set by hand - it never moves a time the admin chose. A meeting saved with a "next plan" and a
    next date also creates the follow-up meeting by itself, and the follow-up is fitted into that day the same way.
Nothing here is ever deleted: a meeting is cancelled, not removed (a task can be removed - it is only a to-do)."""

from datetime import date, datetime, time, timedelta

from flask import Blueprint, abort, g, jsonify, render_template, request

from .auth import visible_clients
from .extensions import db
from .models import PlannerMeeting, PlannerTask, utcnow
from .timeutil import to_local, today_local
from .validation import Fields, api_errors

bp = Blueprint("planner", __name__)
api_errors(bp)

STATUSES = ("planned", "done", "cancelled")
DAY_START = 9 * 60            # the auto scheduler fills 9:00 am ...
DAY_END = 19 * 60             # ... to 7:00 pm
GAP = 15                      # minutes kept free between two things it places
STEP = 5                      # times are picked in 5-minute steps (the app's time picker)
MEETING_MINUTES = 60
TASK_MINUTES = 30
UPCOMING_DAYS = 60            # how far ahead the Upcoming list and "auto-arrange all" look


@bp.before_request
def _admin_only():
    if not g.user.is_admin:
        abort(403, "Only the admin can use the planner.")


# ---------- small helpers ----------

def _mins(t: time) -> int:
    return t.hour * 60 + t.minute


def _clock(m: int) -> time:
    return time(m // 60, m % 60)


def _label(m: int) -> str:
    return _clock(m).strftime("%H:%M")


def _day_or_today(raw) -> date:
    if not raw:
        return today_local()
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        abort(422, "Give the date as YYYY-MM-DD")


def _json_object():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        abort(415, "Send a JSON object")
    return dict(payload)


def _time_field(payload, name, errors, out):
    """An optional "HH:MM" - empty means "not placed yet"."""
    if name not in payload:
        return
    raw = payload[name]
    if raw in (None, ""):
        out[name] = None
        return
    try:
        out[name] = datetime.strptime(str(raw), "%H:%M").time()
    except ValueError:
        errors[name] = "Pick a valid time"


def _now_minutes() -> int:
    local = to_local(utcnow())
    return local.hour * 60 + local.minute


# ---------- the auto scheduler ----------

def _busy(day, skip=None):
    """(start, end) minutes of everything with a time on `day` - cancelled meetings no longer take up the slot."""
    spans = []
    for m in PlannerMeeting.query.filter(PlannerMeeting.meeting_date == day, PlannerMeeting.status != "cancelled", PlannerMeeting.meeting_time.isnot(None)):
        spans.append((_mins(m.meeting_time), _mins(m.meeting_time) + m.duration_min))
    for t in PlannerTask.query.filter(PlannerTask.task_date == day, PlannerTask.task_time.isnot(None)):
        spans.append((_mins(t.task_time), _mins(t.task_time) + t.duration_min))
    return spans


def _first_free(spans, length, earliest):
    """The first minute at or after `earliest` where `length` minutes fit between the spans (a GAP kept around each), or None before the day ends."""
    start = max(DAY_START, earliest)
    start += -start % STEP
    for s, e in sorted(spans):
        if start + length <= s - GAP:
            break
        start = max(start, e + GAP)
        start += -start % STEP
    return start if start + length <= DAY_END else None


def arrange(day):
    """Give a time to every planned meeting and open task on `day` that has none, earliest free slot first (meetings before tasks, in the order they
    were entered). Times the admin set himself are only worked around. Today, nothing is placed in the past. Returns (placed, left_over) counts."""
    meetings = (PlannerMeeting.query.filter(PlannerMeeting.meeting_date == day, PlannerMeeting.status == "planned", PlannerMeeting.meeting_time.is_(None))
                .order_by(PlannerMeeting.id).all())
    tasks = PlannerTask.query.filter(PlannerTask.task_date == day, PlannerTask.done.is_(False), PlannerTask.task_time.is_(None)).order_by(PlannerTask.id).all()
    spans = _busy(day)
    earliest = _now_minutes() if day == today_local() else 0
    placed = left = 0
    for item in [*meetings, *tasks]:
        slot = _first_free(spans, item.duration_min, earliest)
        if slot is None:
            left += 1
            continue
        if isinstance(item, PlannerMeeting):
            item.meeting_time = _clock(slot)
        else:
            item.task_time = _clock(slot)
        spans.append((slot, slot + item.duration_min))
        placed += 1
    return placed, left


# ---------- reading a day ----------

def _day_payload(day):
    meetings = (PlannerMeeting.query.filter_by(meeting_date=day)
                .order_by(PlannerMeeting.meeting_time.is_(None), PlannerMeeting.meeting_time, PlannerMeeting.id).all())
    tasks = PlannerTask.query.filter_by(task_date=day).order_by(PlannerTask.task_time.is_(None), PlannerTask.task_time, PlannerTask.id).all()
    spans = []                                                   # every timed thing that still stands: (start, end, key)
    for m in meetings:
        if m.meeting_time is not None and m.status != "cancelled":
            spans.append((_mins(m.meeting_time), _mins(m.meeting_time) + m.duration_min, ("m", m.id)))
    for t in tasks:
        if t.task_time is not None:
            spans.append((_mins(t.task_time), _mins(t.task_time) + t.duration_min, ("t", t.id)))
    clashing = {key for s, e, key in spans for s2, e2, key2 in spans if key != key2 and s < e2 and s2 < e}
    out_m = [{**m.to_dict(), "clash": ("m", m.id) in clashing} for m in meetings]
    out_t = [{**t.to_dict(), "clash": ("t", t.id) in clashing} for t in tasks]
    return {"date": day.isoformat(), "meetings": out_m, "tasks": out_t, "today": today_local().isoformat(),
            "window": {"start": _label(DAY_START), "end": _label(DAY_END)}}


@bp.get("/planner")
def page():
    return render_template("planner.html")


@bp.get("/api/planner/day")
def day():
    return jsonify(_day_payload(_day_or_today(request.args.get("date"))))


@bp.get("/api/planner/upcoming")
def upcoming():
    """What is coming (planned meetings from today, with the day's open task count) and what still waits for its remark - planned meetings of past days."""
    today = today_local()
    ahead = (PlannerMeeting.query.filter(PlannerMeeting.status == "planned", PlannerMeeting.meeting_date >= today,
                                         PlannerMeeting.meeting_date <= today + timedelta(days=UPCOMING_DAYS))
             .order_by(PlannerMeeting.meeting_date, PlannerMeeting.meeting_time.is_(None), PlannerMeeting.meeting_time, PlannerMeeting.id).all())
    waiting = (PlannerMeeting.query.filter(PlannerMeeting.status == "planned", PlannerMeeting.meeting_date < today)
               .order_by(PlannerMeeting.meeting_date.desc(), PlannerMeeting.id).limit(50).all())
    return jsonify(today=today.isoformat(), meetings=[m.to_dict() for m in ahead], needs_remark=[m.to_dict() for m in waiting])


@bp.get("/api/planner/clients")
def clients():
    """Existing clients to fill a meeting's name, address and contact from - the admin can still type anyone else in."""
    rows = sorted(visible_clients().limit(1000).all(), key=lambda c: c.name.lower())
    return jsonify(clients=[{"id": c.id, "name": c.name, "address": ", ".join(x for x in (c.address, c.city) if x), "contact_no": c.phone or ""} for c in rows])


# ---------- meetings ----------

def _meeting_fields(payload, creating):
    if creating:
        payload.setdefault("client_name", "")
        payload.setdefault("purpose", "")
    f = Fields(payload)
    f.text("client_name", 160, required=True, label="the client's name")
    f.text("address", 500)
    f.text("contact_no", 40)
    f.text("purpose", 300, required=True, label="the purpose of the meeting")
    f.text("place", 200)
    f.text("remark", 4000)
    f.text("next_plan", 500)
    f.choice("status", STATUSES)
    f.date("meeting_date")
    f.date("next_date")
    f.integer("duration_min", 5, 480)
    errors, data = f.errors, f.data
    _time_field(payload, "meeting_time", errors, data)
    if "meeting_date" in payload and data.get("meeting_date") is None and "meeting_date" not in errors:
        errors["meeting_date"] = "Pick the date of the meeting"
    if creating and "meeting_date" not in data and "meeting_date" not in errors:
        errors["meeting_date"] = "Pick the date of the meeting"
    if "duration_min" in data and data["duration_min"] is None:
        data["duration_min"] = MEETING_MINUTES
    if "client_id" in payload:
        raw = payload["client_id"]
        if raw in (None, ""):
            data["client_id"] = None
        elif str(raw).isdigit() and visible_clients().filter_by(id=int(raw)).first():
            data["client_id"] = int(raw)
        else:
            errors["client_id"] = "Pick a client from the list"
    return data, errors


def _meeting_or_404(meeting_id):
    m = db.session.get(PlannerMeeting, meeting_id)
    if m is None:
        abort(404, "Meeting not found")
    return m


def _sync_follow_up(m):
    """The "next schedule plan" with a date becomes a meeting of its own on that day, and is fitted into a free slot there. Cleared again, the
    follow-up is cancelled while it is still only planned. A follow-up already held (or cancelled by hand) is left alone."""
    child = PlannerMeeting.query.filter_by(follow_up_of_id=m.id).order_by(PlannerMeeting.id.desc()).first()
    if m.next_date is None:
        if child is not None and child.status == "planned":
            child.status = "cancelled"
        return
    purpose = (m.next_plan or f"Follow-up: {m.purpose}")[:300]
    if child is None:
        child = PlannerMeeting(logged_on=today_local(), client_id=m.client_id, client_name=m.client_name, address=m.address, contact_no=m.contact_no,
                               purpose=purpose, place=m.place, meeting_date=m.next_date, duration_min=m.duration_min, follow_up_of_id=m.id,
                               created_by_code=g.user.code)
        db.session.add(child)
    elif child.status == "planned":
        if child.meeting_date != m.next_date:
            child.meeting_date, child.meeting_time = m.next_date, None
        child.purpose = purpose
    else:
        return
    db.session.flush()
    arrange(child.meeting_date)


@bp.post("/api/planner/meetings")
def add_meeting():
    payload = _json_object()
    data, errors = _meeting_fields(payload, creating=True)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    data.setdefault("duration_min", MEETING_MINUTES)
    m = PlannerMeeting(logged_on=today_local(), created_by_code=g.user.code, **data)
    db.session.add(m)
    db.session.flush()
    _sync_follow_up(m)
    db.session.commit()
    return jsonify(meeting=m.to_dict()), 201


@bp.patch("/api/planner/meetings/<int:meeting_id>")
def update_meeting(meeting_id):
    m = _meeting_or_404(meeting_id)
    data, errors = _meeting_fields(_json_object(), creating=False)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    plan_before = (m.next_date, m.next_plan)
    day_before = m.meeting_date
    for key, value in data.items():
        setattr(m, key, value)
    if m.meeting_date != day_before and "meeting_time" not in data:
        m.meeting_time = None                         # a moved meeting has to find its own slot on the new day
    db.session.flush()
    if (m.next_date, m.next_plan) != plan_before:
        _sync_follow_up(m)
    db.session.commit()
    return jsonify(meeting=m.to_dict())


# ---------- tasks ----------

def _task_fields(payload, creating):
    if creating:
        payload.setdefault("title", "")
    f = Fields(payload)
    f.text("title", 300, required=True, label="the task")
    f.date("task_date")
    f.integer("duration_min", 5, 240)
    errors, data = f.errors, f.data
    _time_field(payload, "task_time", errors, data)
    if ("task_date" in payload and data.get("task_date") is None and "task_date" not in errors) or (creating and "task_date" not in data and "task_date" not in errors):
        errors["task_date"] = "Pick the day"
    if "duration_min" in data and data["duration_min"] is None:
        data["duration_min"] = TASK_MINUTES
    if "done" in payload:
        if isinstance(payload["done"], bool):
            data["done"] = payload["done"]
        else:
            errors["done"] = "Send true or false"
    return data, errors


def _task_or_404(task_id):
    t = db.session.get(PlannerTask, task_id)
    if t is None:
        abort(404, "Task not found")
    return t


@bp.post("/api/planner/tasks")
def add_task():
    data, errors = _task_fields(_json_object(), creating=True)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    data.setdefault("duration_min", TASK_MINUTES)
    t = PlannerTask(created_by_code=g.user.code, **data)
    db.session.add(t)
    db.session.commit()
    return jsonify(task=t.to_dict()), 201


@bp.patch("/api/planner/tasks/<int:task_id>")
def update_task(task_id):
    t = _task_or_404(task_id)
    data, errors = _task_fields(_json_object(), creating=False)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    day_before = t.task_date
    for key, value in data.items():
        setattr(t, key, value)
    if t.task_date != day_before and "task_time" not in data:
        t.task_time = None
    db.session.commit()
    return jsonify(task=t.to_dict())


@bp.delete("/api/planner/tasks/<int:task_id>")
def delete_task(task_id):
    db.session.delete(_task_or_404(task_id))
    db.session.commit()
    return "", 204


# ---------- the auto scheduler's button ----------

@bp.post("/api/planner/arrange")
def arrange_route():
    """{"date": "YYYY-MM-DD"} arranges that day; {"upcoming": true} every day from today with something still waiting for a time."""
    payload = _json_object()
    if payload.get("upcoming"):
        today = today_local()
        days = set()
        for (d,) in db.session.query(PlannerMeeting.meeting_date).filter(PlannerMeeting.status == "planned", PlannerMeeting.meeting_time.is_(None),
                                                                        PlannerMeeting.meeting_date >= today,
                                                                        PlannerMeeting.meeting_date <= today + timedelta(days=UPCOMING_DAYS)):
            days.add(d)
        for (d,) in db.session.query(PlannerTask.task_date).filter(PlannerTask.done.is_(False), PlannerTask.task_time.is_(None),
                                                                   PlannerTask.task_date >= today, PlannerTask.task_date <= today + timedelta(days=UPCOMING_DAYS)):
            days.add(d)
        placed = left = 0
        for d in sorted(days):
            p, l = arrange(d)
            placed, left = placed + p, left + l
        db.session.commit()
        return jsonify(placed=placed, left=left)
    placed, left = arrange(_day_or_today(payload.get("date")))
    db.session.commit()
    return jsonify(placed=placed, left=left, **_day_payload(_day_or_today(payload.get("date"))))

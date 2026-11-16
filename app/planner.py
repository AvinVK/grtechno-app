"""The admin's meeting planner and scheduler (kohal, 2026-11-16: "a meeting planner and scheduler (auto and manual scheduler) for admin to plan the
day and meetings for future. this should be in me tab"; then: "just have a tile system which can be dragged and moved up or down").

Admin only. A day is a list of tiles - meetings and calls (with the fields of his meeting sheet: date, client name, address, contact no, purpose, place,
date and time of the meeting, remark or feedback, next schedule plan) and simple to-do tasks - in the order he drags them into (`position`, one order
shared by the day's meetings and tasks). A time is optional and only a label; it never reorders anything. A meeting saved with a "next plan" and a next
date creates the follow-up meeting by itself, added to the end of that day.
Nothing here is ever deleted: a meeting is cancelled, not removed (a task can be removed - it is only a to-do)."""

from datetime import date, datetime, timedelta

from flask import Blueprint, abort, g, jsonify, render_template, request
from sqlalchemy import or_

from .auth import visible_clients
from .extensions import db
from .models import PlannerMeeting, PlannerTask
from .timeutil import today_local
from .validation import Fields, api_errors

bp = Blueprint("planner", __name__)
api_errors(bp)

STATUSES = ("planned", "done", "cancelled")
MEETING_KINDS = ("client_meeting", "call")      # "Client meeting" and "Call to make" are meetings ...
TASK_KINDS = ("site_visit", "work")             # ... "Site visit" and "Work to do" are tasks (kohal, 2026-11-16)
AGENDA_DAYS = 365             # how far ahead the plan looks
EARLIER_LIMIT = 100           # how many past, still-open items the plan lists
HISTORY_LIMIT = 200           # meetings shown at once on the Held tab - narrow it with the dates or a client's name for more


@bp.before_request
def _admin_only():
    if not g.user.is_admin:
        abort(403, "Only the admin can use the planner.")


# ---------- small helpers ----------

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
    """An optional "HH:MM" - empty means no time."""
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


def _next_position(day) -> int:
    """The place after the last tile of `day` - tasks and meetings share one order."""
    top = -1
    for model, column in ((PlannerMeeting, PlannerMeeting.meeting_date), (PlannerTask, PlannerTask.task_date)):
        value = db.session.query(db.func.max(model.position)).filter(column == day).scalar()
        if value is not None:
            top = max(top, value)
    return top + 1


def _in_tile_order(meetings, tasks):
    """Meetings and tasks of one day in tile order: by position, then meetings before tasks, then oldest first (rows from before positions all sit at 0)."""
    return sorted([("meeting", m) for m in meetings] + [("task", t) for t in tasks], key=lambda x: (x[1].position, x[0] != "meeting", x[1].id))


def _tiles(day):
    return _in_tile_order(PlannerMeeting.query.filter_by(meeting_date=day).all(), PlannerTask.query.filter_by(task_date=day).all())


# ---------- reading a day ----------

def _can_overlap(a, b) -> bool:
    """A meeting or call and a piece of work to do can happen at the same time (kohal, 2026-11-16: "meeting and work can be parallel") - no clash between
    them. Anything else set for the same time (two meetings, a meeting and a site visit, two site visits) is."""
    (kind_a, row_a), (kind_b, row_b) = a, b
    if kind_a == kind_b:
        return False
    task = row_a if kind_a == "task" else row_b
    return task.kind == "work"


def _payload_of(day, tiles):
    at_time = {}                                                 # a time -> the tiles set for exactly then (a cancelled meeting no longer holds its time)
    for kind, row in tiles:
        at = row.meeting_time if kind == "meeting" else row.task_time
        if at is not None and not (kind == "meeting" and row.status == "cancelled"):
            at_time.setdefault(at, []).append((kind, row))
    clashing = set()
    for same_time in at_time.values():
        for i, a in enumerate(same_time):
            for b in same_time[i + 1:]:
                if not _can_overlap(a, b):
                    clashing.update({(a[0], a[1].id), (b[0], b[1].id)})
    return {"date": day.isoformat(),
            "order": [[kind, row.id] for kind, row in tiles],
            "meetings": [{**row.to_dict(), "clash": ("meeting", row.id) in clashing} for kind, row in tiles if kind == "meeting"],
            "tasks": [{**row.to_dict(), "clash": ("task", row.id) in clashing} for kind, row in tiles if kind == "task"]}


def _day_payload(day):
    return {**_payload_of(day, _tiles(day)), "today": today_local().isoformat()}


@bp.get("/planner")
def page():
    return render_template("planner.html")


@bp.get("/api/planner/day")
def day():
    return jsonify(_day_payload(_day_or_today(request.args.get("date"))))


@bp.get("/api/planner/agenda")
def agenda():
    """The plan, in one scroll (kohal, 2026-11-16: "club day and upcoming tabs"): `earlier` - meetings still planned and tasks not done from days gone
    by, oldest first; then `days` - today (always, even empty) and every later day that has anything, each with its tiles in the order dragged."""
    today = today_local()
    end = today + timedelta(days=AGENDA_DAYS)
    meetings = PlannerMeeting.query.filter(PlannerMeeting.meeting_date >= today, PlannerMeeting.meeting_date <= end).all()
    tasks = PlannerTask.query.filter(PlannerTask.task_date >= today, PlannerTask.task_date <= end).all()
    by_day = {today: ([], [])}
    for m in meetings:
        by_day.setdefault(m.meeting_date, ([], []))[0].append(m)
    for t in tasks:
        by_day.setdefault(t.task_date, ([], []))[1].append(t)
    days = [_payload_of(day, _in_tile_order(*by_day[day])) for day in sorted(by_day)]
    old_meetings = (PlannerMeeting.query.filter(PlannerMeeting.status == "planned", PlannerMeeting.meeting_date < today)
                    .order_by(PlannerMeeting.meeting_date.desc(), PlannerMeeting.id.desc()).limit(EARLIER_LIMIT).all())
    old_tasks = (PlannerTask.query.filter(PlannerTask.done.is_(False), PlannerTask.task_date < today)
                 .order_by(PlannerTask.task_date.desc(), PlannerTask.id.desc()).limit(EARLIER_LIMIT).all())
    earlier = sorted([("meeting", m.meeting_date, m.id, m.to_dict()) for m in old_meetings] + [("task", t.task_date, t.id, t.to_dict()) for t in old_tasks],
                     key=lambda x: (x[1], x[0] != "meeting", x[2]))[-EARLIER_LIMIT:]
    return jsonify(today=today.isoformat(), days=days, earlier=[{"type": kind, **data} for kind, _day, _id, data in earlier])


def _optional_day(name):
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        abort(422, "Give the dates as YYYY-MM-DD")


@bp.get("/api/planner/history")
def history():
    """Meetings and calls already held, newest first (kohal, 2026-11-16: "where do i see held meetings?") - from/to narrow it by date, q by the client's
    name or the purpose; at most HISTORY_LIMIT come back, `more` says there were others."""
    query = PlannerMeeting.query.filter(PlannerMeeting.status == "done")
    start, end = _optional_day("from"), _optional_day("to")
    if start:
        query = query.filter(PlannerMeeting.meeting_date >= start)
    if end:
        query = query.filter(PlannerMeeting.meeting_date <= end)
    text = (request.args.get("q") or "").strip()[:100]
    if text:
        like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"        # a typed % or _ is just a character
        query = query.filter(or_(PlannerMeeting.client_name.ilike(like, escape="\\"), PlannerMeeting.purpose.ilike(like, escape="\\")))
    rows = (query.order_by(PlannerMeeting.meeting_date.desc(), PlannerMeeting.meeting_time.is_(None), PlannerMeeting.meeting_time.desc(), PlannerMeeting.id.desc())
            .limit(HISTORY_LIMIT + 1).all())
    return jsonify(meetings=[m.to_dict() for m in rows[:HISTORY_LIMIT]], more=len(rows) > HISTORY_LIMIT, limit=HISTORY_LIMIT)


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
    f.choice("kind", MEETING_KINDS)
    f.date("meeting_date")
    f.date("next_date")
    errors, data = f.errors, f.data
    _time_field(payload, "meeting_time", errors, data)
    if "meeting_date" in payload and data.get("meeting_date") is None and "meeting_date" not in errors:
        errors["meeting_date"] = "Pick the date of the meeting"
    if creating and "meeting_date" not in data and "meeting_date" not in errors:
        errors["meeting_date"] = "Pick the date of the meeting"
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
    """The "next schedule plan" with a date becomes a meeting of its own, added to the end of that day. Cleared again, the
    follow-up is cancelled while it is still only planned. A follow-up already held (or cancelled by hand) is left alone."""
    child = PlannerMeeting.query.filter_by(follow_up_of_id=m.id).order_by(PlannerMeeting.id.desc()).first()
    if m.next_date is None:
        if child is not None and child.status == "planned":
            child.status = "cancelled"
        return
    purpose = (m.next_plan or f"Follow-up: {m.purpose}")[:300]
    if child is None:
        child = PlannerMeeting(kind=m.kind, logged_on=today_local(), client_id=m.client_id, client_name=m.client_name, address=m.address, contact_no=m.contact_no,
                               purpose=purpose, place=m.place, meeting_date=m.next_date, follow_up_of_id=m.id,
                               position=_next_position(m.next_date), created_by_code=g.user.code)
        db.session.add(child)
    elif child.status == "planned":
        if child.meeting_date != m.next_date:
            child.position = _next_position(m.next_date)
            child.meeting_date = m.next_date
        child.purpose = purpose


@bp.post("/api/planner/meetings")
def add_meeting():
    payload = _json_object()
    data, errors = _meeting_fields(payload, creating=True)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    m = PlannerMeeting(logged_on=today_local(), position=_next_position(data["meeting_date"]), created_by_code=g.user.code, **data)
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
    if data.get("meeting_date") not in (None, m.meeting_date):
        m.position = _next_position(data["meeting_date"])               # a moved meeting goes to the end of its new day
    for key, value in data.items():
        setattr(m, key, value)
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
    f.choice("kind", TASK_KINDS)
    errors, data = f.errors, f.data
    _time_field(payload, "task_time", errors, data)
    if ("task_date" in payload and data.get("task_date") is None and "task_date" not in errors) or (creating and "task_date" not in data and "task_date" not in errors):
        errors["task_date"] = "Pick the day"
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
    t = PlannerTask(position=_next_position(data["task_date"]), created_by_code=g.user.code, **data)
    db.session.add(t)
    db.session.commit()
    return jsonify(task=t.to_dict()), 201


@bp.patch("/api/planner/tasks/<int:task_id>")
def update_task(task_id):
    t = _task_or_404(task_id)
    data, errors = _task_fields(_json_object(), creating=False)
    if errors:
        return jsonify(error="Check the highlighted fields", fields=errors), 422
    if data.get("task_date") not in (None, t.task_date):
        t.position = _next_position(data["task_date"])
    for key, value in data.items():
        setattr(t, key, value)
    db.session.commit()
    return jsonify(task=t.to_dict())


@bp.delete("/api/planner/tasks/<int:task_id>")
def delete_task(task_id):
    db.session.delete(_task_or_404(task_id))
    db.session.commit()
    return "", 204


# ---------- dragging tiles ----------

@bp.post("/api/planner/order")
def set_order():
    """{"date": "YYYY-MM-DD", "items": [["meeting", 3], ["task", 7], ...]} - the day's tiles in the order they were dragged into. Anything of that day
    left out of the list (added in the meantime) keeps its place after the listed ones."""
    payload = _json_object()
    day = _day_or_today(payload.get("date"))
    items = payload.get("items")
    if not isinstance(items, list):
        abort(422, "Send the tiles in their new order")
    models = {"meeting": PlannerMeeting, "task": PlannerTask}
    ordered, seen = [], set()
    for entry in items:
        if not (isinstance(entry, list) and len(entry) == 2 and entry[0] in models and isinstance(entry[1], int) and not isinstance(entry[1], bool)):
            abort(422, "Each tile is a kind and an id")
        row = db.session.get(models[entry[0]], entry[1])
        row_day = None if row is None else (row.meeting_date if entry[0] == "meeting" else row.task_date)
        if row is None or row_day != day:
            abort(422, "That tile is not on this day")
        if (entry[0], entry[1]) in seen:
            abort(422, "A tile is listed twice")
        seen.add((entry[0], entry[1]))
        ordered.append(row)
    ordered += [row for kind, row in _tiles(day) if (kind, row.id) not in seen]
    for position, row in enumerate(ordered):
        row.position = position
    db.session.commit()
    return jsonify(_day_payload(day))

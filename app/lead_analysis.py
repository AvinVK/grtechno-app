"""Lead analysis (kohal, 2026-11-05: "do the same analysis for leads as well. have graph of leads per month. leads per source. time
spent on each stage. brought by count of each lead by each sales man").

A page of charts over the leads the signed-in person may see (auth.visible_leads - everything for the admin and the wider roles,
only their own for a salesperson), worked out from the live records each time and never stored:

  - Leads over time: how many leads came in - by day for the last 30 days or this month, by month for the last 3, 6 or 12 months
    (its own range, picked on the chart; kohal, 2026-11-05).
  - Leads per source: where they came from.
  - Time on each stage: how long leads stayed in each pipeline stage before moving on, from the stage changes recorded on each lead
    (Activity kind "stage"), plus how many are sitting in each stage now and for how long.
  - Brought by: for each person who took the enquiry (Lead.enquired_by, else whoever entered it), how many leads, and how those
    turned out.

The period (all time, last 12 / 6 / 3 months or 30 days) cuts the leads by the day they came in, for everything but the over-time chart."""

import re
from collections import Counter
from datetime import date, datetime, timedelta
from statistics import median

from flask import Blueprint, abort, g, jsonify, render_template, request

from .auth import visible_leads
from .constants import CLOSED_STAGES, OPEN_STAGES
from .extensions import db
from .models import Lead, settings_for_client, utcnow
from .modules import check_module
from .projects import brought_by
from .timeutil import months_back, to_local, today_local
from .validation import api_errors

bp = Blueprint("lead_analysis", __name__)
api_errors(bp)

# Months back for the longer periods; "30d" is the 30 days up to today (the page opens on it - kohal, 2026-11-06).
PERIODS = {"all": None, "12": 12, "6": 6, "3": 3, "30d": "30d"}
# The over-time chart's own ranges: key -> (label, unit). "30d" is the 30 days up to today, "1" is the calendar month so far.
TRENDS = {"30d": ("Last 30 days", "day"), "1": ("This month", "day"), "3": ("Last 3 months", "month"),
          "6": ("Last 6 months", "month"), "12": ("Last 12 months", "month")}
STAGE_CHANGE = re.compile(r"^Stage changed:\s*(.+?)\s*(?:→|->)\s*(.+?)\s*$")
MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@bp.before_request
def _leads_service():
    check_module("leads")


@bp.get("/lead-analysis")
def page():
    return render_template("lead_analysis.html")


def _local_day(dt):
    return to_local(dt).date() if isinstance(dt, datetime) else dt


def _stage_history(lead):
    """[(stage, entered_at)] in order: New enquiry at creation, then each recorded change into a stage. Times are naive UTC."""
    steps = [("New enquiry", lead.created_at)]
    for a in sorted((a for a in lead.activities if a.kind == "stage"), key=lambda a: (a.created_at, a.id)):
        m = STAGE_CHANGE.match(a.text or "")
        if m:
            steps.append((m.group(2), a.created_at))
    return steps


def _stage_times(leads, now):
    """Per open stage: how long leads stayed in it before moving on (average and median days, over every completed stay) and who is
    in it right now (count and average days so far)."""
    stays = {s: [] for s in OPEN_STAGES}
    here = {s: [] for s in OPEN_STAGES}
    for lead in leads:
        steps = _stage_history(lead)
        for (stage, entered), (_, left) in zip(steps, steps[1:]):
            if stage in stays and left >= entered:
                stays[stage].append((left - entered).total_seconds() / 86400)
        last_stage, last_at = steps[-1]
        if lead.stage in here and last_stage == lead.stage:          # only when the record really reaches the stage they are in
            here[lead.stage].append(max((now - last_at).total_seconds(), 0) / 86400)
    rows = []
    for s in OPEN_STAGES:
        d = stays[s]
        rows.append({"stage": s, "avg_days": round(sum(d) / len(d), 1) if d else None, "median_days": round(median(d), 1) if d else None,
                     "stays": len(d), "now": len(here[s]), "now_avg_days": round(sum(here[s]) / len(here[s]), 1) if here[s] else None})
    return rows


def _trend(leads, today, key):
    """Leads received per day (30 days / this month) or per month (3, 6, 12 months), oldest first."""
    label, unit = TRENDS[key]
    received = [_local_day(l.created_at) for l in leads]
    if unit == "day":
        start = today - timedelta(days=29) if key == "30d" else today.replace(day=1)
        per_day = Counter(d for d in received if d >= start)
        points, d = [], start
        while d <= today:
            points.append({"key": d.isoformat(), "label": f"{d.day} {MONTH_ABBR[d.month]}", "count": per_day.get(d, 0)})
            d += timedelta(days=1)
    else:
        n = int(key)
        first = months_back(today, n - 1)
        per_month = Counter((d.year, d.month) for d in received if d >= first)
        points = []
        for i in range(n):
            m = months_back(today, n - 1 - i)
            points.append({"key": f"{m.year}-{m.month:02d}", "label": f"{MONTH_ABBR[m.month]} {str(m.year)[2:]}", "count": per_month.get((m.year, m.month), 0)})
    return {"range": key, "label": label, "unit": unit, "points": points, "total": sum(p["count"] for p in points)}


def _with_success(person):
    """Success rate (kohal, 2026-11-06): of the leads this person brought that have been decided, the share that were won -
    won / (won + lost), as a whole percent. Leads still open do not count either way; None until one has been decided."""
    closed = person["won"] + person["lost"]
    return {**person, "success_rate": round(person["won"] * 100 / closed) if closed else None}


@bp.get("/api/lead-analysis")
def analysis():
    period = request.args.get("period") or "all"
    if period not in PERIODS:
        abort(422, "Pick a valid period")
    trend = request.args.get("trend") or "12"
    if trend not in TRENDS:
        abort(422, "Pick a valid range")
    today = today_local()
    leads = visible_leads().order_by(Lead.id).all()
    cur = settings_for_client()["currency"]

    # Leads over time has a range of its own.
    # Everything else is over the chosen period.
    span = PERIODS[period]
    since = today - timedelta(days=29) if span == "30d" else months_back(today, span - 1) if span else None
    scoped = [l for l in leads if since is None or _local_day(l.created_at) >= since]

    sources = Counter((l.source or "").strip() or "Not set" for l in scoped)
    people = {}
    for l in scoped:
        who = brought_by(l)
        name = who["name"] if who else "Not set"
        row = people.setdefault(name, {"name": name, "total": 0, "won": 0, "lost": 0, "open": 0})
        row["total"] += 1
        row["won" if l.stage == "Won" else "lost" if l.stage == "Lost" else "open"] += 1

    return jsonify(
        period=period, total=len(scoped), currency=cur,
        periods=[{"value": "all", "label": "All time"}, {"value": "12", "label": "Last 12 months"},
                 {"value": "6", "label": "Last 6 months"}, {"value": "3", "label": "Last 3 months"},
                 {"value": "30d", "label": "Last 30 days"}],
        trend=_trend(leads, today, trend),
        trends=[{"value": k, "label": v[0]} for k, v in TRENDS.items()],
        sources=[{"source": k, "count": v} for k, v in sorted(sources.items(), key=lambda kv: (-kv[1], kv[0].lower()))],
        stage_times=_stage_times(scoped, utcnow()),
        brought_by=sorted((_with_success(p) for p in people.values()), key=lambda r: (-r["total"], r["name"].lower())),
        scope="everyone's leads" if (g.user.is_admin or g.user.sees_all or g.user.role_key == "sales_office") else "your leads",
    )

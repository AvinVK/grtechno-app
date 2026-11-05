"""Monthly reports in Excel (kohal, 2026-11-05: "monthly reports in excel format to document everything happening in
the business. lets start from leads").

Admin only. /reports lists the reports and a month to pick; each report is one workbook downloaded from
/api/reports/<name>?month=YYYY-MM. Today there is one, Leads; the others (projects, fooding, petrol, inventory...)
are added here the same way - a function returning the sheets, registered in REPORTS.

Everything is worked out from what is already on file, never stored, so a report for a past month is always rebuilt
from the live records. A month is the calendar month in local time (timeutil)."""

import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, Response, abort, g, jsonify, render_template, request

from .constants import CLOSED_STAGES, OPEN_STAGES, STAGES
from .models import Activity, Lead, settings_for_client
from .timeutil import to_local, today_local
from .validation import api_errors
from .xlsx import build_workbook

bp = Blueprint("reports", __name__)
api_errors(bp)

MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@bp.before_request
def _admin_only():
    if not g.user.is_admin:
        abort(403, "Only the admin can see the reports.")


def _month_or_default(raw):
    """(year, month) from "YYYY-MM", or this month when none is given - a bad value is a 422, not a guess."""
    if not raw:
        today = today_local()
        return today.year, today.month
    m = MONTH_RE.match(str(raw))
    if not m:
        abort(422, "Pick a month like 2026-11")
    return int(m.group(1)), int(m.group(2))


def _month_label(year, month):
    return date(year, month, 1).strftime("%B %Y")


def _local_date(value):
    """A stored UTC timestamp as the local calendar day, or None."""
    if value is None:
        return None
    return to_local(value).date() if isinstance(value, datetime) else value


def _in_month(day, year, month):
    return day is not None and (day.year, day.month) == (year, month)


def _name(lead):
    return lead.company or lead.contact_name or f"Lead {lead.id}"


def _site(lead):
    return lead.survey.site_name if lead.survey and lead.survey.site_name else ""


def _services(lead):
    return ", ".join(s.name for s in lead.services) if lead.services else (lead.service or "")


def _deal_value(lead):
    """What a deal is worth: the finalized negotiation round's estimate, else the quoted value."""
    finalized = [n for n in lead.negotiations if n.finalized and n.estimate is not None]
    if finalized:
        return finalized[-1].estimate
    return lead.est_value


def _money(value):
    return float(value) if value is not None else None


def _counts(title, counter, head=("", "Leads")):
    rows = [[title, None], [head[0] or "Item", head[1]]]
    rows += [[k or "(not set)", v] for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0] or ""))] or [["(none)", 0]]
    return rows


# ---------- the Leads report ----------

def leads_report(year, month):
    leads = Lead.query.order_by(Lead.id).all()
    cur = settings_for_client()["currency"]
    label = _month_label(year, month)

    new = [l for l in leads if _in_month(_local_date(l.created_at), year, month)]
    surveyed = [l for l in leads if l.survey and _in_month(l.survey.survey_date, year, month)]
    quoted = [l for l in leads if _in_month(l.quote_sent_date, year, month)]
    rounds = [(l, n) for l in leads for n in l.negotiations if _in_month(n.date, year, month)]
    closed = [l for l in leads if l.stage in CLOSED_STAGES and _in_month(_local_date(l.closed_at), year, month)]
    won = [l for l in closed if l.stage == "Won"]
    lost = [l for l in closed if l.stage == "Lost"]
    advances = [l for l in leads if l.advance_amount is not None and _in_month(l.advance_date, year, month)]
    moves = [(a, l) for l in leads for a in l.activities if a.kind == "stage" and _in_month(_local_date(a.created_at), year, month)]
    moves.sort(key=lambda t: t[0].created_at)

    open_now = [l for l in leads if l.stage in OPEN_STAGES]
    today = today_local()
    overdue = [l for l in open_now if l.follow_up_date and l.follow_up_date < today]

    def total(values):
        return float(sum((v for v in values if v is not None), Decimal("0")))

    summary = [
        ["Leads report", None],
        ["Month", label],
        ["Generated", today],
        [None, None],
        [f"In {label}", None],
        ["New leads received", len(new)],
        ["Site surveys done", len(surveyed)],
        ["Quotes sent", len(quoted)],
        [f"Value of quotes sent ({cur})", total(l.est_value for l in quoted)],
        ["Negotiation rounds held", len(rounds)],
        ["Leads won", len(won)],
        [f"Value won ({cur})", total(_deal_value(l) for l in won)],
        ["Leads lost", len(lost)],
        [f"Advances received ({cur})", total(l.advance_amount for l in advances)],
        [None, None],
    ]
    summary += _counts("New leads by source", Counter(l.source for l in new)) + [[None, None]]
    summary += _counts("New leads by service", Counter(s for l in new for s in (_services(l).split(", ") if _services(l) else ["(not set)"]))) + [[None, None]]
    summary += [["All leads by stage today", None], ["Stage", "Leads"]]
    by_stage = Counter(l.stage for l in leads)
    summary += [[stage, by_stage.get(stage, 0)] for stage in STAGES]
    summary += [["Open leads with an overdue follow-up", len(overdue)]]
    bold = {i for i, r in enumerate(summary) if r[0] in (
        "Leads report", f"In {label}", "New leads by source", "New leads by service", "All leads by stage today")}
    bold |= {i for i, r in enumerate(summary) if i and summary[i - 1][0] in ("New leads by source", "New leads by service", "All leads by stage today")}

    sheets = [{"name": "Summary", "rows": summary, "bold_rows": bold}]

    sheets.append({"name": "New leads", "freeze": 1, "bold_rows": {0}, "rows": [
        ["Lead #", "Received", "Company", "Contact person", "Phone", "Email", "Services", "Source", "Enquired by", "Owner",
         "Stage now", f"Est. value ({cur})", "Follow-up"]] + [
        [l.id, _local_date(l.created_at), l.company, l.contact_name, l.phone, l.email, _services(l), l.source,
         l.enquired_by.name if l.enquired_by else "", l.owner.name if l.owner else "", l.stage, _money(l.est_value), l.follow_up_date]
        for l in new]})

    sheets.append({"name": "Site surveys", "freeze": 1, "bold_rows": {0}, "rows": [
        ["Lead #", "Survey date", "Company", "Site name", "Site category", "Surveyed by", "Site representative", "Role", "Phone",
         "City", "District", "State", "Pincode", "Address", "Photos"]] + [
        [l.id, l.survey.survey_date, l.company or l.contact_name, l.survey.site_name, l.survey.site_category,
         l.survey.surveyor.name if l.survey.surveyor else "", l.survey.rep_name, l.survey.rep_role, l.survey.rep_phone,
         l.survey.site_city, l.survey.site_district, l.survey.site_state, l.survey.site_pincode, l.survey.site_address,
         len(l.survey.photos)] for l in surveyed]})

    sheets.append({"name": "Quotes sent", "freeze": 1, "bold_rows": {0}, "rows": [
        ["Lead #", "Quote sent", "Company", "Site name", "Services", f"Quoted value ({cur})", "Stage now"]] + [
        [l.id, l.quote_sent_date, l.company or l.contact_name, _site(l), _services(l), _money(l.est_value), l.stage] for l in quoted]})

    sheets.append({"name": "Negotiations", "freeze": 1, "bold_rows": {0}, "rows": [
        ["Lead #", "Round date", "Company", "Site name", "Round", "Authorized person", f"Estimate ({cur})", "Finalized"]] + [
        [l.id, n.date, l.company or l.contact_name, _site(l), n.round_no, n.authorized_person, _money(n.estimate), bool(n.finalized)]
        for l, n in rounds]})

    sheets.append({"name": "Won and lost", "freeze": 1, "bold_rows": {0}, "rows": [
        ["Lead #", "Closed", "Outcome", "Company", "Site name", "Services", f"Value ({cur})", "Work order no.", "Work order date",
         f"Advance ({cur})", "Advance date", "Account", "Client", "Project"]] + [
        [l.id, _local_date(l.closed_at), l.stage, l.company or l.contact_name, _site(l), _services(l), _money(_deal_value(l)),
         l.work_order_no, l.work_order_date, _money(l.advance_amount), l.advance_date, l.advance_mode,
         l.client.name if l.client else "", l.project.code if l.project else ""] for l in closed]})

    sheets.append({"name": "Stage movements", "freeze": 1, "bold_rows": {0}, "rows": [
        ["When", "Lead #", "Company", "Site name", "What happened"]] + [
        [to_local(a.created_at), l.id, l.company or l.contact_name, _site(l), a.text] for a, l in moves]})
    return sheets


REPORTS = {
    "leads": {"title": "Leads", "about": "New leads, site surveys, quotes, negotiations, wins and losses, and every stage move.",
              "build": leads_report},
}


@bp.get("/reports")
def page():
    return render_template("reports.html")


@bp.get("/api/reports")
def list_reports():
    today = today_local()
    months = []
    y, m = today.year, today.month
    for _ in range(24):                                         # this month and the 23 before it
        months.append({"value": f"{y}-{m:02d}", "label": _month_label(y, m)})
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return jsonify(reports=[{"key": k, "title": r["title"], "about": r["about"]} for k, r in REPORTS.items()],
                   months=months, current=months[0]["value"])


@bp.get("/api/reports/<name>")
def download(name):
    report = REPORTS.get(name)
    if report is None:
        abort(404)
    year, month = _month_or_default(request.args.get("month"))
    data = build_workbook(report["build"](year, month))
    filename = f"{report['title'].lower().replace(' ', '-')}-report-{year}-{month:02d}.xlsx"
    return Response(data, mimetype=XLSX_TYPE, headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})

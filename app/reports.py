"""Monthly reports in Excel (kohal, 2026-11-05: "monthly reports in excel format to document everything happening in
the business. lets start from leads").

Admin only. /reports lists the reports and a month to pick; each report is one workbook downloaded from
/api/reports/<name>?month=YYYY-MM. Today there is one, Leads; the others (projects, fooding, petrol, inventory...)
are added here the same way - a function returning the sheets, registered in REPORTS.

Everything is worked out from what is already on file, never stored, so a report for a past month is always rebuilt
from the live records. A month is the calendar month in local time (timeutil)."""

import re
from collections import Counter
import calendar
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, Response, abort, g, jsonify, render_template, request

from .constants import CLOSED_STAGES, OPEN_STAGES, STAGES
from .models import Attendance, Lead, MaterialMovement, Project, ProjectExpense, Worker, WorkerAttendance, settings_for_client
from .projects import _expenses, _material_costs, _wage_expenses
from .reference_data import PROJECT_STATUSES
from .constants import ADHOC_STATUSES
from .payroll import DAY_RATE_TYPES, _day_by_day, _day_rate_slot_row, _salaried_earned, salaried_month
from .workers import EMPLOYMENT_TYPES, _period
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


# ---------- the Payroll and wages report ----------

CATEGORY_LABEL = {"daily_wages": "Daily wages", "contractor": "Contractor (daily rate)", "regular": "Salaried"}


def _month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def payroll_report(year, month):
    """Daily-wage (and contractor, who are on a day rate too) and salaried employees for one month, worked out with
    the same rules the Payroll screen uses - a day rate for every day present (no Sunday credit), two half-month
    pay periods; a monthly salary cut for absences, plus house rent / petrol (app/payroll.py's salaried_month) - so the file
    always agrees with what the app shows."""
    cur = settings_for_client()["currency"]
    label = _month_label(year, month)
    first, last = date(year, month, 1), _month_end(year, month)
    _, data_until = _period()
    today = today_local()
    data_until_end = min(today, data_until) if data_until else None
    slots = [(date(year, month, 1), date(year, month, 15), f"1-15 {first.strftime('%b %Y')}"),
             (date(year, month, 16), last, f"16-{last.day} {first.strftime('%b %Y')}")]

    workers = (Worker.query.filter(Worker.employment_type.in_(EMPLOYMENT_TYPES), Worker.wage_amount.isnot(None))
               .order_by(Worker.name).all())
    day_rate = [w for w in workers if w.employment_type in DAY_RATE_TYPES]
    salaried = [w for w in workers if w.employment_type == "regular"]
    role = lambda w: w.role.name if w.role else ""

    # Daily wages: one row per employee per pay period, plus their attendance for the month.
    day_rows, att_rows = [], []
    for w in day_rate:
        for start, end, slot_label in slots:
            r = _day_rate_slot_row(w, start, end, slot_label, data_until_end)
            day_rows.append([w.name, CATEGORY_LABEL[w.employment_type], role(w), r["wage_amount"], slot_label, r["days"], r["absent"],
                             r["earned"], r["paid"], r["outstanding"]])
        marks, present, absent, hours = [], 0, 0, 0.0
        for d in _day_by_day(w, first, last, data_until_end):
            if d["not_yet"]:
                marks.append("-")
            elif d["present"]:
                marks.append("P")
                present += 1
            else:
                marks.append("A")
                absent += 1
            hours += d["hours"] or 0
        att_rows.append([w.name, CATEGORY_LABEL[w.employment_type]] + marks + [present, absent, round(hours, 1)])
    day_total = ["Total", None, None, None, None, sum(r[5] for r in day_rows), sum(r[6] for r in day_rows),
                 round(sum(r[7] for r in day_rows), 2), round(sum(r[8] for r in day_rows), 2), round(sum(r[9] for r in day_rows), 2)]

    # Salaried: the month's salary, what was paid in it, and what stands owed at its end.
    sal_rows = []
    for w in salaried:
        wage = float(w.wage_amount)
        month_pay = salaried_month(w, year, month, data_until_end)
        due = float(month_pay["net"] + month_pay["allowance"]) if month_pay else 0.0
        paid_in = float(sum((p.amount for p in w.payments if p.paid_date and first <= p.paid_date <= last), Decimal("0")))
        paid_to_date = float(sum((p.amount for p in w.payments if p.paid_date and p.paid_date <= last), Decimal("0")))
        earned_to_date = float(_salaried_earned(w, last, data_until_end))
        sal_rows.append([w.name, role(w), wage, due, paid_in, paid_to_date, round(earned_to_date - paid_to_date, 2)])
    sal_total = ["Total", None, round(sum(r[2] for r in sal_rows), 2), round(sum(r[3] for r in sal_rows), 2), round(sum(r[4] for r in sal_rows), 2),
                 round(sum(r[5] for r in sal_rows), 2), round(sum(r[6] for r in sal_rows), 2)]

    # Every payment actually made in the month, whoever it was to.
    pays = [(p, w) for w in Worker.query.order_by(Worker.name).all() for p in w.payments if p.paid_date and first <= p.paid_date <= last]
    pays.sort(key=lambda t: (t[0].paid_date, t[1].name))
    by_category = Counter()
    by_account = Counter()
    for p, w in pays:
        by_category[CATEGORY_LABEL.get(w.employment_type, "Other")] += float(p.amount)
        by_account[p.mode or "(not set)"] += float(p.amount)

    summary = [
        ["Payroll and wages report", None],
        ["Month", label],
        ["Generated", today],
        [None, None],
        ["Daily wages (including contractors on a day rate)", None],
        ["Employees", len(day_rate)],
        [f"Earned in {label} ({cur})", day_total[7]],
        [f"Paid for these periods ({cur})", day_total[8]],
        [f"Still due for these periods ({cur})", day_total[9]],
        ["Days worked", day_total[5]],
        ["Days absent", day_total[6]],
        [None, None],
        ["Salaried", None],
        ["Employees", len(salaried)],
        [f"Salary for {label} ({cur})", sal_total[3]],
        [f"Paid in {label} ({cur})", sal_total[4]],
        [f"Owed at the end of {label} ({cur})", sal_total[6]],
        [None, None],
        [f"Paid out in {label}, by category", None], ["Category", cur]]
    summary += [[k, round(v, 2)] for k, v in sorted(by_category.items())] or [["(nothing paid)", 0]]
    summary += [["Total paid out", round(sum(by_category.values()), 2)], [None, None],
                [f"Paid out in {label}, by account", None], ["Account", cur]]
    summary += [[k, round(v, 2)] for k, v in sorted(by_account.items())] or [["(nothing paid)", 0]]
    titles = {f"Paid out in {label}, by category", f"Paid out in {label}, by account", "Payroll and wages report",
              "Daily wages (including contractors on a day rate)", "Salaried"}
    bold = {i for i, r in enumerate(summary) if r[0] in titles or r[0] in ("Category", "Account", "Total paid out")}

    return [
        {"name": "Summary", "rows": summary, "bold_rows": bold},
        {"name": "Daily wages", "freeze": 1, "bold_rows": {0, len(day_rows) + 1}, "rows": [
            ["Employee", "Type", "Role", f"Daily rate ({cur})", "Pay period", "Days counted", "Days absent", f"Earned ({cur})",
             f"Paid for period ({cur})", f"Outstanding ({cur})"]] + day_rows + [day_total]},
        {"name": "Attendance (daily wages)", "freeze": 1, "bold_rows": {0}, "rows": [
            ["Employee", "Type"] + [str(d) for d in range(1, last.day + 1)] + ["Present", "Absent", "Hours logged"]] + att_rows
            + [[None], ["P = present (paid), A = absent, - = no attendance data for that day. Daily wages are paid for days worked only, Sundays included."]]},
        {"name": "Salaried", "freeze": 1, "bold_rows": {0, len(sal_rows) + 1}, "rows": [
            ["Employee", "Role", f"Monthly salary ({cur})", f"Salary for month ({cur})", f"Paid in month ({cur})",
             f"Paid to date ({cur})", f"Owed at month end ({cur})"]] + sal_rows + [sal_total]},
        {"name": "Payments", "freeze": 1, "bold_rows": {0}, "rows": [
            ["Paid on", "Employee", "Category", "Label", "For pay period starting", f"Amount ({cur})", "Account / mode", "Comments"]] + [
            [p.paid_date, w.name, CATEGORY_LABEL.get(w.employment_type, "Other"), p.label, p.period_start, float(p.amount), p.mode, p.comments]
            for p, w in pays]},
    ]


# ---------- the Projects report ----------

STATUS_LABEL = {"planned": "Planned", "running": "Running", "on_hold": "On hold", "final_estimate_sent": "Final estimate sent",
                "completed": "Completed", "unbilled": "Unbilled (adhoc)", "billed": "Billed (adhoc)"}
PROJECT_STATUS_OPTIONS = [{"value": "all", "label": "All"}] + [
    {"value": k, "label": STATUS_LABEL.get(k, k)} for k in list(PROJECT_STATUSES) + list(ADHOC_STATUSES)]


def projects_report(year, month, status="all"):
    """Every project (of the chosen status) with what went into it in the month: material issued (net of returns),
    who was there and for how long, daily-wage cost, commission and other expenses - the same figures a project's own
    Materials, Team and Expense tabs show, cut to the month, with the totals to date alongside. Sheets are sorted by
    project so each project's rows sit together, and have filter buttons to pick one."""
    cur = settings_for_client()["currency"]
    label = _month_label(year, month)
    first, last = date(year, month, 1), _month_end(year, month)
    q = Project.query.order_by(Project.id)
    if status != "all":
        q = q.filter(Project.status == status)
    projects = q.all()
    by_id = {p.id: p for p in projects}
    ids = list(by_id)
    name_of = lambda p: f"{p.code} · {p.title}" if p.title else p.code

    # Materials issued to the project (a return comes back negative, so the total nets out).
    moves = (MaterialMovement.query.filter(MaterialMovement.project_id.in_(ids), MaterialMovement.status == "approved",
                                           MaterialMovement.kind.in_(("out", "in")),
                                           MaterialMovement.entry_date >= first, MaterialMovement.entry_date <= last)
             .order_by(MaterialMovement.project_id, MaterialMovement.entry_date, MaterialMovement.id).all()) if ids else []
    material_rows = [[by_id[m.project_id].code, by_id[m.project_id].title, m.entry_date, m.material.name, "Issued" if m.kind == "out" else "Returned",
                      float(m.quantity), m.material.unit, float(m.rate), float(m.amount) if m.kind == "out" else -float(m.amount),
                      m.given_by.name if m.given_by else "", m.note] for m in moves]
    material_by_project = Counter()
    for m in moves:
        material_by_project[m.project_id] += float(m.amount) if m.kind == "out" else -float(m.amount)

    # Who was on site: the app's own check-ins (approved) and WhatsApp days (present), by day and by person.
    app_days = (Attendance.query.filter(Attendance.project_id.in_(ids), Attendance.status == "approved",
                                        Attendance.work_date >= first, Attendance.work_date <= last)
                .order_by(Attendance.project_id, Attendance.work_date, Attendance.id).all()) if ids else []
    wa_days = (WorkerAttendance.query.filter(WorkerAttendance.project_id.in_(ids), WorkerAttendance.status == "present",
                                             WorkerAttendance.work_date >= first, WorkerAttendance.work_date <= last)
               .order_by(WorkerAttendance.project_id, WorkerAttendance.work_date, WorkerAttendance.id).all()) if ids else []
    workers_by_user = {w.user_code: w for w in Worker.query.filter(Worker.user_code.isnot(None)).all()}

    detail = []                                   # (project_id, date, person, source, in, out, hours)
    people = {}                                   # (project_id, person key) -> {worker, name, days:set, hours}
    for a in app_days:
        w = workers_by_user.get(a.user_code)
        key = (a.project_id, ("w", w.id) if w else ("u", a.user_code))
        person = people.setdefault(key, {"worker": w, "name": w.name if w else (a.user.name if a.user else a.user_code), "days": set(), "hours": 0.0})
        person["days"].add(a.work_date)
        person["hours"] += a.hours or 0
        detail.append((a.project_id, a.work_date, person["name"], "App check-in", to_local(a.check_in_at) if a.check_in_at else None,
                       to_local(a.check_out_at) if a.check_out_at else None, a.hours))
    for a in wa_days:
        key = (a.project_id, ("w", a.worker_id))
        person = people.setdefault(key, {"worker": a.worker, "name": a.worker.name, "days": set(), "hours": 0.0})
        person["days"].add(a.work_date)
        person["hours"] += a.hours or 0
        detail.append((a.project_id, a.work_date, person["name"], "WhatsApp", a.check_in_at, a.check_out_at, a.hours))
    detail.sort(key=lambda r: (r[0], r[1], r[2]))

    attendance_rows, wage_rows, wage_by_project = [], [], Counter()
    for (pid, _), person in sorted(people.items(), key=lambda kv: (kv[0][0], kv[1]["name"].lower())):
        w = person["worker"]
        days = len(person["days"])
        costed = bool(w and w.employment_type == "daily_wages" and w.wage_amount is not None)     # same rule as a project's own wage cost
        cost = float((w.wage_amount * days).quantize(Decimal("0.01"))) if costed else None
        attendance_rows.append([by_id[pid].code, by_id[pid].title, person["name"], CATEGORY_LABEL.get(w.employment_type, "") if w else "",
                                days, round(person["hours"], 1), float(w.wage_amount) if costed else None, cost])
        if costed:
            wage_rows.append([by_id[pid].code, by_id[pid].title, None, "Daily wages", person["name"], f"{days} day{'s' if days != 1 else ''} at {float(w.wage_amount):g}", cost])
            wage_by_project[pid] += cost
    attendance_detail = [[by_id[pid].code, by_id[pid].title, d, person, src, cin, cout, hrs] for pid, d, person, src, cin, cout, hrs in detail]

    # Commission and any other money paid out of the project, entered on its Expense tab.
    exps = (ProjectExpense.query.filter(ProjectExpense.project_id.in_(ids), ProjectExpense.entry_date >= first, ProjectExpense.entry_date <= last)
            .order_by(ProjectExpense.project_id, ProjectExpense.entry_date, ProjectExpense.id).all()) if ids else []
    commission = [e for e in exps if e.kind == "commission"]
    other = [e for e in exps if e.kind != "commission"]
    commission_rows = [[by_id[e.project_id].code, by_id[e.project_id].title, e.entry_date, e.worker.name if e.worker else "", float(e.percent),
                        float(e.basis_amount), float(e.amount), e.note, e.created_by.name if e.created_by else ""] for e in commission]
    commission_by_project, other_by_project = Counter(), Counter()
    for e in commission:
        commission_by_project[e.project_id] += float(e.amount)
    for e in other:
        other_by_project[e.project_id] += float(e.amount)
    expense_rows = sorted(wage_rows + [[by_id[e.project_id].code, by_id[e.project_id].title, e.entry_date, e.kind.replace("_", " ").title(),
                                         e.worker.name if e.worker else "", e.note, float(e.amount)] for e in other], key=lambda r: (r[0], str(r[2] or "")))

    # One line per project: what it is worth and has received, what went into it this month, and the cost to date.
    summary_rows = []
    for p in projects:
        month_cost = material_by_project[p.id] + wage_by_project[p.id] + commission_by_project[p.id] + other_by_project[p.id]
        to_date = _material_costs(p)[1] + _wage_expenses(p)[1] + _expenses(p)[1]
        value = float(p.net_amount) if p.net_amount is not None else None
        received = float(p.paid_amount)
        summary_rows.append([p.code, p.title, p.client.name if p.client else "", STATUS_LABEL.get(p.status, p.status),
                             p.manager.name if p.manager else "", value, received, round(value - received, 2) if value is not None else None,
                             round(material_by_project[p.id], 2), round(wage_by_project[p.id], 2), round(commission_by_project[p.id], 2),
                             round(other_by_project[p.id], 2), round(month_cost, 2), round(to_date, 2)])
    totals = ["Total", None, None, None, None, None, None, None] + [round(sum(r[i] for r in summary_rows), 2) for i in range(8, 14)]
    status_label = next(o["label"] for o in PROJECT_STATUS_OPTIONS if o["value"] == status)
    head = [["Projects report", None], ["Month", label], ["Project status", status_label], ["Projects included", len(projects)],
            ["Generated", today_local()], [None, None]]
    table_header = ["Project", "Title", "Client", "Status", "Manager", f"Value ({cur})", f"Received to date ({cur})", f"Still to receive ({cur})",
                    f"Materials in {label} ({cur})", f"Daily wages in {label} ({cur})", f"Commission in {label} ({cur})",
                    f"Other expenses in {label} ({cur})", f"Total cost in {label} ({cur})", f"Cost to date, all time ({cur})"]
    rows = head + [table_header] + summary_rows + [totals]

    def sheet(name, header, body, **kw):
        return {"name": name, "freeze": 1, "bold_rows": {0}, "filter": True, "rows": [header] + body, **kw}

    return [
        {"name": "Summary", "rows": rows, "bold_rows": {0, len(head), len(rows) - 1}},
        sheet("Materials used", ["Project", "Title", "Date", "Material", "Issued / returned", "Quantity", "Unit", f"Rate ({cur})", f"Amount ({cur})", "Given by", "Note"], material_rows),
        sheet("Attendance", ["Project", "Title", "Person", "Type", "Days present", "Hours logged", f"Daily rate ({cur})", f"Wage cost ({cur})"], attendance_rows),
        sheet("Attendance by day", ["Project", "Title", "Date", "Person", "Source", "Checked in", "Checked out", "Hours"], attendance_detail),
        sheet("Expenses", ["Project", "Title", "Date", "Kind", "Person", "Detail", f"Amount ({cur})"], expense_rows),
        sheet("Commission", ["Project", "Title", "Date", "Paid to", "Percent", f"Basis ({cur})", f"Amount ({cur})", "Note", "Entered by"], commission_rows),
    ]


REPORTS = {
    "leads": {"title": "Leads", "about": "New leads, site surveys, quotes, negotiations, wins and losses, and every stage move.",
              "build": leads_report},
    "payroll": {"title": "Payroll and wages", "about": "Daily wages and salaried employees: earned, paid and still due, attendance, and every payment made.",
                "build": payroll_report},
    "projects": {"title": "Projects", "about": "For each project: material used, attendance and daily wages, other expenses and commission, with totals to date.",
                 "build": projects_report, "filters": [{"key": "status", "label": "Project status", "options": PROJECT_STATUS_OPTIONS}]},
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
    return jsonify(reports=[{"key": k, "title": r["title"], "about": r["about"], "filters": r.get("filters", [])} for k, r in REPORTS.items()],
                   months=months, current=months[0]["value"])


@bp.get("/api/reports/<name>")
def download(name):
    report = REPORTS.get(name)
    if report is None:
        abort(404)
    year, month = _month_or_default(request.args.get("month"))
    chosen = {}
    for f in report.get("filters", []):                         # each filter is optional (first option) but never a guess
        value = request.args.get(f["key"]) or f["options"][0]["value"]
        if value not in {o["value"] for o in f["options"]}:
            abort(422, f"Pick a valid {f['label'].lower()}")
        chosen[f["key"]] = value
    data = build_workbook(report["build"](year, month, **chosen))
    suffix = "".join(f"-{v}" for k, v in chosen.items() if v != "all")
    filename = f"{report['title'].lower().replace(' ', '-')}-report-{year}-{month:02d}{suffix}.xlsx"
    return Response(data, mimetype=XLSX_TYPE, headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})

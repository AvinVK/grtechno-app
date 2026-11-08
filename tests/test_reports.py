"""Monthly Excel reports (kohal, 2026-11-05) - the workbook writer and the Leads report."""

import io
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import (
    Activity, Attendance, Client, Lead, LeadNegotiation, LeadSurvey, Material, MaterialMovement, Project, ProjectExpense,
    ProjectPayment, Service, Worker, WorkerAttendance, WorkerPayment,
)
from conftest import make_user
from app.xlsx import build_workbook

openpyxl = pytest.importorskip("openpyxl")        # only used here, to read the file back independently of the writer


def _read(data):
    return openpyxl.load_workbook(io.BytesIO(data), data_only=True)


def test_the_workbook_writer_makes_a_file_excel_can_open():
    data = build_workbook([
        {"name": "People", "rows": [["Name", "Paid", "On"], ["Asha & Co <1>", Decimal("1200.50"), date(2026, 11, 3)], ["Ravi", 40, None]],
         "bold_rows": {0}, "freeze": 1},
        {"name": "People", "rows": [["again"]]},                                    # a repeated name is made unique
        {"name": "Bad/Name:*?", "rows": []},
    ])
    wb = _read(data)
    assert wb.sheetnames == ["People", "People 2", "Bad-Name---"]
    ws = wb["People"]
    assert ws["A1"].value == "Name" and ws["A1"].font.b is True
    assert ws["A2"].value == "Asha & Co <1>" and ws["B2"].value == 1200.5 and ws["B3"].value == 40
    assert ws["C2"].value == datetime(2026, 11, 3) and ws["C3"].value is None
    assert ws.freeze_panes == "A2"


def test_control_characters_in_text_do_not_break_the_file():
    wb = _read(build_workbook([{"name": "S", "rows": [["bad\x00\x0bchars ok"]]}]))
    assert wb["S"]["A1"].value == "badchars ok"


def _lead(**kw):
    lead = Lead(contact_name=kw.pop("contact", "Contact"), company=kw.pop("company", "Acme"), phone="9999900000",
                source=kw.pop("source", "Referral"), **kw)
    db.session.add(lead)
    db.session.flush()
    return lead


def _seed(app):
    """November 2026: two new leads (one of them surveyed, quoted, negotiated and won), one lead that is lost, and one
    October lead that only had its quote go out in November."""
    with app.app_context():
        svc = Service(name="Fire alarm")
        db.session.add(svc)
        won = _lead(company="Won Co", source="Website", stage="Won", created_at=datetime(2026, 11, 2, 6, 0),
                    est_value=Decimal("100000"), quote_sent_date=date(2026, 11, 8), closed_at=datetime(2026, 11, 20, 6, 0),
                    work_order_no="WO-1", work_order_date=date(2026, 11, 15), advance_amount=Decimal("25000"),
                    advance_date=date(2026, 11, 16), advance_mode="GR BB")
        won.services.append(svc)
        db.session.add(LeadSurvey(lead=won, survey_date=date(2026, 11, 5), site_name="Plant One", site_city="Pune"))
        db.session.add(LeadNegotiation(lead=won, round_no=1, date=date(2026, 11, 12), authorized_person="Boss",
                                       estimate=Decimal("90000"), finalized=True))
        db.session.add(Activity(lead=won, kind="stage", text="Stage changed: Negotiation → Work order & advance",
                                created_at=datetime(2026, 11, 15, 6, 0)))
        _lead(company="Lost Co", source="Website", stage="Lost", created_at=datetime(2026, 11, 3, 6, 0), closed_at=datetime(2026, 11, 25, 6, 0))
        _lead(company="Oct Co", source="Referral", stage="Quote sent", created_at=datetime(2026, 10, 20, 6, 0),
              est_value=Decimal("5000"), quote_sent_date=date(2026, 11, 2))
        db.session.commit()


def test_the_leads_report_counts_what_happened_in_the_month(app, admin_client):
    _seed(app)
    res = admin_client.get("/api/reports/leads?month=2026-11")
    assert res.status_code == 200 and res.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "leads-report-2026-11.xlsx" in res.headers["Content-Disposition"]
    wb = _read(res.data)
    assert wb.sheetnames == ["Summary", "New leads", "Site surveys", "Quotes sent", "Negotiations", "Won and lost", "Stage movements"]

    summary = {row[0].value: row[1].value for row in wb["Summary"].iter_rows() if row[0].value}
    assert summary["Month"] == "November 2026"
    assert summary["New leads received"] == 2 and summary["Site surveys done"] == 1 and summary["Quotes sent"] == 2
    assert summary["Value of quotes sent (₹)"] == 105000 and summary["Negotiation rounds held"] == 1
    assert summary["Leads won"] == 1 and summary["Value won (₹)"] == 90000          # the finalized round, not the first quote
    assert summary["Leads lost"] == 1 and summary["Advances received (₹)"] == 25000

    new = [[c.value for c in row] for row in wb["New leads"].iter_rows(min_row=2)]
    assert sorted(r[2] for r in new) == ["Lost Co", "Won Co"]                      # Oct Co was received in October
    assert [r[0] for r in wb["Quotes sent"].iter_rows(min_row=2, max_col=1)] and wb["Quotes sent"].max_row == 3
    survey = [c.value for c in wb["Site surveys"][2]]
    assert survey[3] == "Plant One" and survey[9] == "Pune"
    closed = {row[3].value: row[2].value for row in wb["Won and lost"].iter_rows(min_row=2)}
    assert closed == {"Won Co": "Won", "Lost Co": "Lost"}
    assert wb["Stage movements"].max_row == 2


def test_a_month_with_nothing_still_downloads(app, admin_client):
    res = admin_client.get("/api/reports/leads?month=2020-01")
    assert res.status_code == 200
    wb = _read(res.data)
    assert wb["New leads"].max_row == 1                                              # just the header
    assert {row[0].value: row[1].value for row in wb["Summary"].iter_rows() if row[0].value}["New leads received"] == 0


def test_no_month_means_this_month_and_a_bad_one_is_refused(admin_client):
    assert admin_client.get("/api/reports/leads").status_code == 200
    assert admin_client.get("/api/reports/leads?month=2026-13").status_code == 422
    assert admin_client.get("/api/reports/leads?month=november").status_code == 422
    assert admin_client.get("/api/reports/nothing").status_code == 404


def test_only_the_admin_can_see_reports(client, accounts_client, admin_client):
    for who in (client, accounts_client):
        assert who.get("/reports").status_code == 403
        assert who.get("/api/reports").status_code == 403
        assert who.get("/api/reports/leads").status_code == 403
    assert admin_client.get("/reports").status_code == 200
    data = admin_client.get("/api/reports").get_json()
    assert [r["key"] for r in data["reports"]] == ["leads", "payroll", "projects"] and len(data["months"]) == 24 and data["current"] == data["months"][0]["value"]


def test_the_admin_has_reports_under_manage_on_the_me_tab(admin_client, client):
    """kohal, 2026-11-05: "have report under manage tab" - a row in Manage, not a Services tile."""
    html = admin_client.get("/me").data.decode()
    assert 'class="me-row" href="/reports"' in html and 'class="me-tile" href="/reports"' not in html
    assert b'href="/reports"' not in client.get("/me").data


# ---------- the Payroll and wages report (kohal, 2026-11-05) ----------

def _seed_payroll(app):
    """October 2026 (a month wholly in the past, after payroll's own Oct 1 start): Deepak on a 500 day rate, present Mon 5th
    to Thu 8th, with an 800 advance paid for the first half; Anita on a 30,000 salary, present every working day but Tue 13th
    and Wed 14th, paid 10,000 in October and 5,000 in September; and a contractor with no attendance."""
    with app.app_context():
        deepak = Worker(name="Deepak Daily", category="manpower", employment_type="daily_wages", wage_amount=Decimal("500"))
        anita = Worker(name="Anita Salaried", category="staff", employment_type="regular", wage_amount=Decimal("30000"))
        contractor = Worker(name="Chandu Contractor", category="manpower", employment_type="contractor", wage_amount=Decimal("700"))
        pusher = Worker(name="Data Until Pusher", category="manpower")
        db.session.add_all([deepak, anita, contractor, pusher])
        db.session.flush()
        for day in (5, 6, 7, 8):
            db.session.add(WorkerAttendance(worker=deepak, work_date=date(2026, 10, day), check_in_lat=21.1, check_in_lng=79.0))
        db.session.add(WorkerAttendance(worker=pusher, work_date=date(2026, 10, 31), check_in_lat=21.1, check_in_lng=79.0))
        for day in range(1, 32):
            if date(2026, 10, day).weekday() != 6 and day not in (13, 14):
                db.session.add(WorkerAttendance(worker=anita, work_date=date(2026, 10, day), check_in_lat=21.1, check_in_lng=79.0))
        db.session.add(WorkerPayment(worker=deepak, label="Advance", amount=Decimal("800"), paid_date=date(2026, 10, 10),
                                     period_start=date(2026, 10, 1), mode="Cash"))
        db.session.add(WorkerPayment(worker=anita, label="October salary part", amount=Decimal("10000"), paid_date=date(2026, 10, 20), mode="GR BB"))
        db.session.add(WorkerPayment(worker=anita, label="September salary part", amount=Decimal("5000"), paid_date=date(2026, 9, 28), mode="GR BB"))
        db.session.commit()


def test_the_payroll_report_follows_the_payroll_screens_rules(app, admin_client):
    _seed_payroll(app)
    res = admin_client.get("/api/reports/payroll?month=2026-10")
    assert res.status_code == 200 and "payroll-and-wages-report-2026-10.xlsx" in res.headers["Content-Disposition"]
    wb = _read(res.data)
    assert wb.sheetnames == ["Summary", "Daily wages", "Attendance (daily wages)", "Salaried", "Payments"]

    rows = {(r[0].value, r[4].value): [c.value for c in r] for r in wb["Daily wages"].iter_rows(min_row=2) if r[0].value != "Total"}
    first_half = rows[("Deepak Daily", "1-15 Oct 2026")]
    # 4 days present + the Sundays of the 4th and 11th not worked = 6 days; 15 days less 2 Sundays less 4 present = 9 absent
    assert first_half[5] == 6 and first_half[6] == 9 and first_half[7] == 3000 and first_half[8] == 800 and first_half[9] == 2200
    second_half = rows[("Deepak Daily", "16-31 Oct 2026")]
    assert second_half[5] == 2 and second_half[7] == 1000 and second_half[8] == 0                # only the 18th and 25th, Sundays
    assert rows[("Chandu Contractor", "1-15 Oct 2026")][1] == "Contractor (daily rate)"          # a contractor is on a day rate too
    # the contractor (700 a day, nobody present) earns only their four Sundays: 4 x 700 = 2,800; Deepak 3,000 + 1,000
    total = [c.value for c in wb["Daily wages"][wb["Daily wages"].max_row]]
    assert total[0] == "Total" and total[7] == 6800 and total[8] == 800 and total[9] == 6000

    deepak = next(r for r in wb["Attendance (daily wages)"].iter_rows(values_only=True) if r[0] == "Deepak Daily")
    marks = ["A"] * 3 + ["S"] + ["P"] * 4 + ["A"] * 2 + ["S"] + ["A"] * 6 + ["S"] + ["A"] * 6 + ["S"] + ["A"] * 6
    assert list(deepak[2:33]) == marks and len(marks) == 31
    assert deepak[33:37] == (4, 4, 23, 0)                                                        # present, Sundays credited, absent, hours

    salaried = [c.value for c in wb["Salaried"][2]]
    # salary cut for her 2 absences (kohal, 2026-11-08): 30,000 / 31 = 968 a day x 29 days = 28,072
    assert salaried[0] == "Anita Salaried" and salaried[3] == 28072 and salaried[4] == 10000     # paid in October
    assert salaried[5] == 15000 and salaried[6] == 13072                                         # to date incl. September; owed at month end

    payments = [[c.value for c in r] for r in wb["Payments"].iter_rows(min_row=2)]
    assert [(p[1], p[2], p[5]) for p in payments] == [("Deepak Daily", "Daily wages", 800), ("Anita Salaried", "Salaried", 10000)]

    summary = {r[0].value: r[1].value for r in wb["Summary"].iter_rows() if r[0].value}
    assert summary["Month"] == "October 2026" and summary["Total paid out"] == 10800
    assert summary["Salary for October 2026 (₹)"] == 28072 and summary["Owed at the end of October 2026 (₹)"] == 13072


# ---------- the Projects report (kohal, 2026-11-05) ----------

def _seed_projects(app):
    """October 2026. Plant A (running, 1,00,000, 40,000 received): sand issued 10 and 2 returned at 20 in October and 25 more
    in September; Deepak (500 a day) on site the 5th and 6th by WhatsApp and the 6th and 7th by app check-in, Anita (salaried)
    on the 8th; 5,000 commission and 300 of food on the 18th and 20th. Plant B (completed): 100 of sand issued."""
    with app.app_context():
        client = Client(name="Acme")
        db.session.add(client)
        db.session.flush()
        a = Project(client=client, title="Plant A", status="running", estimated_amount=Decimal("100000"))
        b = Project(client=client, title="Plant B", status="completed")
        db.session.add_all([a, b])
        db.session.flush()
        db.session.add(ProjectPayment(project=a, label="Advance", amount=Decimal("40000"), paid_date=date(2026, 10, 1)))
        sand = Material(name="Sand", unit="bags")
        db.session.add(sand)
        db.session.flush()

        def move(project, kind, qty, day, month=10):
            db.session.add(MaterialMovement(material=sand, project_id=project.id, kind=kind, quantity=Decimal(qty), rate=Decimal("20"),
                                            amount=Decimal(qty) * 20, entry_date=date(2026, month, day), status="approved", requested=True))
        move(a, "out", 10, 10)
        move(a, "in", 2, 12)
        move(a, "out", 25, 20, month=9)
        move(b, "out", 5, 3)

        user = make_user("Deepak App User")
        deepak = Worker(name="Deepak Daily", category="manpower", employment_type="daily_wages", wage_amount=Decimal("500"), user_code=user.code)
        anita = Worker(name="Anita Salaried", category="staff", employment_type="regular", wage_amount=Decimal("30000"))
        db.session.add_all([deepak, anita])
        db.session.flush()
        for day in (5, 6):
            db.session.add(WorkerAttendance(worker=deepak, work_date=date(2026, 10, day), project_id=a.id))
        db.session.add(WorkerAttendance(worker=anita, work_date=date(2026, 10, 8), project_id=a.id))
        for day in (6, 7):
            db.session.add(Attendance(user_code=user.code, work_date=date(2026, 10, day), project_id=a.id, status="approved",
                                      check_in_at=datetime(2026, 10, day, 4, 0), check_out_at=datetime(2026, 10, day, 12, 0)))
        db.session.add(ProjectExpense(project=a, worker=anita, kind="commission", percent=Decimal("5"), basis_amount=Decimal("100000"),
                                      amount=Decimal("5000"), entry_date=date(2026, 10, 18)))
        db.session.add(ProjectExpense(project=a, kind="food", percent=Decimal("0"), basis_amount=Decimal("0"), amount=Decimal("300"),
                                      entry_date=date(2026, 10, 20), note="Site tea"))
        db.session.commit()


def _project_rows(wb):
    ws = wb["Summary"]
    header = next(i for i, r in enumerate(ws.iter_rows(values_only=True), 1) if r[0] == "Project")
    return {r[1]: list(r) for r in ws.iter_rows(min_row=header + 1, values_only=True) if r[0] and r[0] != "Total"}


def test_the_projects_report_covers_materials_attendance_expenses_and_commission(app, admin_client):
    _seed_projects(app)
    res = admin_client.get("/api/reports/projects?month=2026-10")
    assert res.status_code == 200 and "projects-report-2026-10.xlsx" in res.headers["Content-Disposition"]
    wb = _read(res.data)
    assert wb.sheetnames == ["Summary", "Materials used", "Attendance", "Attendance by day", "Expenses", "Commission"]

    rows = _project_rows(wb)
    a = rows["Plant A"]
    # value, received, still to receive, then this month: materials 200 - 40 returned, wages 3 days x 500, commission, food, total
    assert a[3] == "Running" and a[5] == 100000 and a[6] == 40000 and a[7] == 60000
    assert a[8] == 160 and a[9] == 1500 and a[10] == 5000 and a[11] == 300 and a[12] == 6960
    assert a[13] == 7460                                           # to date adds September's 25 bags (500) to everything above
    b = rows["Plant B"]
    assert b[3] == "Completed" and b[8] == 100 and b[12] == 100 and b[5] is None

    materials = [[c.value for c in r] for r in wb["Materials used"].iter_rows(min_row=2)]
    assert [(m[0], m[4], m[5], m[8]) for m in materials] == [("PRJ-0001", "Issued", 10, 200), ("PRJ-0001", "Returned", 2, -40), ("PRJ-0002", "Issued", 5, 100)]
    assert wb["Materials used"].auto_filter.ref == "A1:K4"

    attendance = {(r[0].value, r[2].value): [c.value for c in r] for r in wb["Attendance"].iter_rows(min_row=2)}
    deepak = attendance[("PRJ-0001", "Deepak Daily")]
    assert deepak[4] == 3 and deepak[5] == 16 and deepak[6] == 500 and deepak[7] == 1500     # the 6th, seen twice, counts once
    anita = attendance[("PRJ-0001", "Anita Salaried")]
    assert anita[3] == "Salaried" and anita[4] == 1 and anita[7] is None                     # salaried staff are not costed to a project
    assert wb["Attendance by day"].max_row == 1 + 5                                           # every record: 2 WhatsApp + 2 app + Anita

    expenses = [[c.value for c in r] for r in wb["Expenses"].iter_rows(min_row=2)]
    assert sorted((e[3], e[6]) for e in expenses) == [("Daily wages", 1500), ("Food", 300)]
    commission = [[c.value for c in r] for r in wb["Commission"].iter_rows(min_row=2)]
    assert len(commission) == 1 and commission[0][3] == "Anita Salaried" and commission[0][4] == 5 and commission[0][6] == 5000


def test_the_projects_report_filters_by_status(app, admin_client):
    _seed_projects(app)
    running = _project_rows(_read(admin_client.get("/api/reports/projects?month=2026-10&status=running").data))
    assert list(running) == ["Plant A"]
    res = admin_client.get("/api/reports/projects?month=2026-10&status=completed")
    assert "projects-report-2026-10-completed.xlsx" in res.headers["Content-Disposition"]
    wb = _read(res.data)
    assert list(_project_rows(wb)) == ["Plant B"] and wb["Materials used"].max_row == 2          # only Plant B's issue
    assert wb["Commission"].max_row == 1
    assert list(_project_rows(_read(admin_client.get("/api/reports/projects?month=2026-10&status=all").data))) == ["Plant A", "Plant B"]


def test_a_bad_status_is_refused_and_the_filters_are_listed(admin_client):
    assert admin_client.get("/api/reports/projects?status=nonsense").status_code == 422
    projects = next(r for r in admin_client.get("/api/reports").get_json()["reports"] if r["key"] == "projects")
    assert [f["key"] for f in projects["filters"]] == ["status"]
    assert [o["value"] for o in projects["filters"][0]["options"]][:3] == ["all", "planned", "running"]
    leads = next(r for r in admin_client.get("/api/reports").get_json()["reports"] if r["key"] == "leads")
    assert leads["filters"] == []


def test_a_month_with_nothing_still_downloads_for_projects(app, admin_client):
    _seed_projects(app)
    wb = _read(admin_client.get("/api/reports/projects?month=2020-01").data)
    assert wb["Materials used"].max_row == 1 and wb["Commission"].max_row == 1
    assert all(r[12] == 0 for r in _project_rows(wb).values())

"""Monthly Excel reports (kohal, 2026-11-05) - the workbook writer and the Leads report."""

import io
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Activity, Lead, LeadNegotiation, LeadSurvey, Service
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
    assert [r["key"] for r in data["reports"]] == ["leads"] and len(data["months"]) == 24 and data["current"] == data["months"][0]["value"]


def test_the_admin_has_reports_under_manage_on_the_me_tab(admin_client, client):
    """kohal, 2026-11-05: "have report under manage tab" - a row in Manage, not a Services tile."""
    html = admin_client.get("/me").data.decode()
    assert 'class="me-row" href="/reports"' in html and 'class="me-tile" href="/reports"' not in html
    assert b'href="/reports"' not in client.get("/me").data

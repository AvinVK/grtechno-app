"""The Transactions report (kohal, 2026-11-25: "every and any expense and every and any received ... the pdf and date filter and other stuff").
See app/transactions_report.py - it is built from the same ledger the Accounts page shows."""

import io
import re
import zipfile
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import AccountTransfer, Client, Project, ProjectPayment, Worker, WorkerPayment

RANGE = {"from": "2026-10-01", "to": "2026-10-31"}


def _seed():
    """Money received 5,000 (GR BB) and 900 (an older mode, no account); spent 1,200 (GR BB) and 700 (CASH); one self transfer that is neither."""
    c = Client(name="Ravi Traders", address="x")
    p = Project(client=c, title="Shop fit-out", status="running")
    w = Worker(name="Sunny Welder", employment_type="daily_wages")
    db.session.add_all([c, p, w])
    db.session.flush()
    p.payments.append(ProjectPayment(label="Advance", amount=Decimal("5000"), mode="GR BB", paid_date=date(2026, 10, 20), position=1))
    p.payments.append(ProjectPayment(label="Old cheque", amount=Decimal("900"), mode="Cheque", paid_date=date(2026, 10, 21), position=2))
    p.payments.append(ProjectPayment(label="In September", amount=Decimal("111"), mode="GR BB", paid_date=date(2026, 9, 30), position=3))
    w.payments.append(WorkerPayment(label="Week 1", amount=Decimal("1200"), mode="GR BB", paid_date=date(2026, 10, 25), position=1))
    w.payments.append(WorkerPayment(label="Week 2", amount=Decimal("700"), mode="CASH", paid_date=date(2026, 10, 26), position=2))
    db.session.add(AccountTransfer(from_account="GR BB", to_account="CASH", amount=Decimal("300"), note="top up", entry_date=date(2026, 10, 27)))
    db.session.commit()


def _view(client, **extra):
    res = client.get("/api/reports/transactions/view", query_string={**RANGE, **extra})
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_only_the_admin_can_open_it(admin_client, manager_client):
    assert admin_client.get("/api/reports/transactions/view").status_code == 200
    for url in ("/api/reports/transactions/view", "/api/reports/transactions", "/api/reports/transactions?format=pdf"):
        assert manager_client.get(url).status_code == 403


def test_it_is_listed_with_a_pdf_download(admin_client):
    reports = {r["key"]: r for r in admin_client.get("/api/reports").get_json()["reports"]}
    assert reports["transactions"]["title"] == "Transactions" and reports["transactions"]["range"] is True and reports["transactions"]["pdf"] is True
    assert reports["inventory"]["pdf"] is False and reports["leads"]["pdf"] is False


def test_everything_received_and_spent_between_the_dates_is_added_up(admin_client):
    _seed()
    d = _view(admin_client)
    assert (d["received"], d["spent"], d["net"], d["count"]) == (5900.0, 1900.0, 4000.0, 4)      # the transfer and the September payment are not in it
    assert [day["date"] for day in d["days"]] == ["2026-10-20", "2026-10-21", "2026-10-25", "2026-10-26"]       # oldest first
    assert [(e["reason"], e["party"], e["account"]) for e in d["days"][1]["entries"]] == [("Project payment", "Ravi Traders", "")]       # no account recorded
    assert d["currency"] and d["accounts"][-1] == {"value": "none", "label": "(no account)"}


def test_the_dates_limit_it(admin_client):
    _seed()
    one_day = _view(admin_client, **{"from": "2026-10-25", "to": "2026-10-25"})
    assert (one_day["received"], one_day["spent"], one_day["count"]) == (0.0, 1200.0, 1)
    with_september = _view(admin_client, **{"from": "2026-09-30", "to": "2026-10-31"})
    assert with_september["received"] == 6011.0


def test_it_can_show_only_what_came_in_or_only_what_went_out(admin_client):
    _seed()
    got = _view(admin_client, kind="in")
    assert (got["received"], got["spent"], got["count"]) == (5900.0, 0.0, 2)
    spent = _view(admin_client, kind="out")
    assert (spent["received"], spent["spent"], spent["count"]) == (0.0, 1900.0, 2)


def test_it_can_show_one_account_or_the_entries_with_none(admin_client):
    _seed()
    bb = _view(admin_client, account="GR BB")
    assert (bb["received"], bb["spent"]) == (5000.0, 1200.0)            # the 300 transfer out of it is not an expense
    cash = _view(admin_client, account="CASH")
    assert (cash["received"], cash["spent"]) == (0.0, 700.0)
    none = _view(admin_client, account="none")
    assert (none["received"], none["spent"], none["count"]) == (900.0, 0.0, 1)


def test_it_agrees_with_the_accounts_page(admin_client):
    """What every account's ledger says came in or went out (less self transfers) is what the report says in all."""
    _seed()
    credits = debits = 0.0
    for a in admin_client.get("/api/accounts").get_json()["accounts"]:
        for e in admin_client.get("/api/accounts/detail", query_string={"name": a["name"]}).get_json()["entries"]:
            if e["reason"] != "Self transfer":
                credits += e["amount"] if e["kind"] == "credit" else 0
                debits += e["amount"] if e["kind"] == "debit" else 0
    d = _view(admin_client, **{"from": "2026-01-01", "to": "2026-10-31"})
    no_account = 900.0                                                   # the one the accounts have no ledger for
    assert d["received"] == credits + no_account and d["spent"] == debits


def test_bad_filters_are_refused_not_guessed(admin_client):
    for bad in ({"from": "soon"}, {"to": "2999-01-01"}, {"from": "2026-10-31", "to": "2026-10-01"}, {"kind": "all-of-it"}, {"account": "Piggy bank"},
                {"from": "2020-01-01", "to": "2026-10-31"}):
        assert admin_client.get("/api/reports/transactions/view", query_string=bad).status_code == 422, bad


def _sheets(data):
    zf = zipfile.ZipFile(io.BytesIO(data))
    return re.findall(r'<sheet name="([^"]+)"', zf.read("xl/workbook.xml").decode()), zf


def test_the_excel_has_a_sheet_for_the_summary_everything_received_and_spent(admin_client):
    _seed()
    res = admin_client.get("/api/reports/transactions", query_string=RANGE)
    assert res.status_code == 200 and "spreadsheetml" in res.mimetype
    assert res.headers["Content-Disposition"] == 'attachment; filename="transactions-report-2026-10-01-to-2026-10-31.xlsx"'
    names, zf = _sheets(res.data)
    assert names == ["Summary", "All entries", "Received", "Spent"]
    text = " ".join(zf.read(n).decode() for n in zf.namelist() if n.startswith("xl/") and n.endswith((".xml", ".xml.rels")))
    assert "Ravi Traders" in text and "Sunny Welder" in text and "Project payment" in text and "(no account)" in text


def test_the_excel_follows_the_filters(admin_client):
    _seed()
    names, _zf = _sheets(admin_client.get("/api/reports/transactions", query_string={**RANGE, "kind": "in", "account": "GR BB"}).data)
    assert names == ["Summary", "All entries", "Received"]
    res = admin_client.get("/api/reports/transactions", query_string={**RANGE, "kind": "out"})
    assert _sheets(res.data)[0] == ["Summary", "All entries", "Spent"]
    assert res.headers["Content-Disposition"].endswith('-spent.xlsx"')
    assert admin_client.get("/api/reports/transactions", query_string={"kind": "nope"}).status_code == 422


def test_the_pdf_is_a_real_pdf_with_the_figures(admin_client):
    _seed()
    res = admin_client.get("/api/reports/transactions", query_string={**RANGE, "format": "pdf"})
    assert res.status_code == 200 and res.mimetype == "application/pdf"
    assert res.headers["Content-Disposition"] == 'attachment; filename="transactions-report-2026-10-01-to-2026-10-31.pdf"'
    assert res.data.startswith(b"%PDF-1.4") and res.data.rstrip().endswith(b"%%EOF")
    assert b"Ravi Traders" in res.data and b"Sunny Welder" in res.data
    assert b"Rs. 5,900" in res.data and b"Rs. 1,900" in res.data and b"Rs. 4,000" in res.data     # received, spent, net
    assert b"/Count 1 " in res.data


def test_a_long_list_runs_over_onto_more_pages(admin_client):
    c = Client(name="Ravi Traders", address="x")
    p = Project(client=c, title="Shop fit-out", status="running")
    db.session.add_all([c, p])
    db.session.flush()
    for i in range(120):
        p.payments.append(ProjectPayment(label=f"Part {i}", amount=Decimal("10"), mode="GR BB", paid_date=date(2026, 10, 1 + i % 28), position=i + 1))
    db.session.commit()
    res = admin_client.get("/api/reports/transactions", query_string={**RANGE, "format": "pdf"})
    pages = int(re.search(rb"/Count (\d+) ", res.data).group(1))
    assert pages >= 3 and f"Page {pages} of {pages}".encode() in res.data
    assert b"Rs. 1,200" in res.data


def test_an_empty_range_still_gives_a_pdf_and_a_workbook(admin_client):
    assert admin_client.get("/api/reports/transactions", query_string={**RANGE, "format": "pdf"}).data.startswith(b"%PDF")
    assert _sheets(admin_client.get("/api/reports/transactions", query_string=RANGE).data)[0][0] == "Summary"
    d = _view(admin_client)
    assert (d["received"], d["spent"], d["days"]) == (0.0, 0.0, [])


def test_only_a_report_with_a_pdf_can_be_downloaded_as_one(admin_client):
    assert admin_client.get("/api/reports/inventory", query_string={"format": "pdf"}).status_code == 422

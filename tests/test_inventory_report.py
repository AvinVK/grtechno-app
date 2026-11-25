"""Inventory report (kohal, 2026-11-14: "inside this one inventory report, there should be 3 sub report (in excel 3 sheets). first, have from date and to
date - 1. per day stock in 2. per day stock out i.e, assigned to project - allocation 3. at any selected date whats the inventory status - also have
material search for point 1 and 2") - see app/inventory_report.py."""

import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.extensions import db
from app.models import Material, MaterialMovement
from app.timeutil import today_local
from test_projects import make_project


def _material(name, unit="bags", qty="0", rate="0", active=True):
    m = Material(name=name, unit=unit, stock_qty=Decimal(qty), avg_rate=Decimal(rate), is_active=active)
    db.session.add(m)
    db.session.flush()
    return m


def _move(material, kind, qty, rate, day, project_id=None, status="approved", gst="0", requested=False, bill=""):
    amount = Decimal(qty) * Decimal(rate)
    gst_amount = (amount * Decimal(gst) / 100).quantize(Decimal("0.01"))
    db.session.add(MaterialMovement(material=material, kind=kind, quantity=Decimal(qty), rate=Decimal(rate), amount=amount, project_id=project_id,
                                    entry_date=day, status=status, gst_percent=Decimal(gst), gst_amount=gst_amount, total_cost=amount + gst_amount,
                                    requested=requested, bill_no=bill))


def _get(client, part, **query):
    res = client.get("/api/inventory/report", query_string={"part": part, **query})
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def _nov(d):
    return date(2026, 11, d)


# ---------- 1. stock in, day by day ----------

def test_stock_in_is_every_purchase_between_the_dates_day_by_day(app, admin_client):
    with app.app_context():
        cement, pipe = _material("Cement"), _material("Pipe", "mtr")
        _move(cement, "in", "10", "50", _nov(3), gst="18", bill="B-1")               # 500 + 90
        _move(pipe, "in", "20", "10", _nov(3))                                       # 200
        _move(cement, "in", "5", "60", _nov(9))                                      # 300
        _move(cement, "in", "99", "50", _nov(1))                                     # before the range
        _move(cement, "in", "99", "50", _nov(12))                                    # after it
        _move(cement, "in", "99", "50", _nov(4), status="pending")                   # not moved stock
        _move(cement, "in", "99", "50", _nov(5), status="rejected")
        db.session.commit()
    d = _get(admin_client, "in", **{"from": "2026-11-02", "to": "2026-11-10"})["report"]
    assert [(day["date"], day["total"], len(day["entries"])) for day in d["days"]] == [("2026-11-03", 790.0, 2), ("2026-11-09", 300.0, 1)]
    first = next(e for e in d["days"][0]["entries"] if e["name"] == "Cement")
    assert (first["quantity"], first["rate"], first["amount"], first["gst"], first["total"], first["bill_no"]) == (10.0, 50.0, 500.0, 90.0, 590.0, "B-1")
    assert (d["count"], d["amount"], d["gst"], d["total"]) == (3, 1000.0, 90.0, 1090.0)


def test_a_return_from_a_project_and_an_issue_are_not_stock_in(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        cement = _material("Cement")
        _move(cement, "out", "4", "50", _nov(4), project_id=pid, requested=True)
        _move(cement, "in", "2", "50", _nov(6), project_id=pid, requested=True)
        db.session.commit()
    assert _get(admin_client, "in", **{"from": "2026-11-01", "to": "2026-11-14"})["report"]["days"] == []


def test_stock_in_and_stock_out_can_be_narrowed_to_one_material(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        cement, pipe = _material("Cement"), _material("Pipe", "mtr")
        _move(cement, "in", "10", "50", _nov(3))
        _move(pipe, "in", "20", "10", _nov(3))
        _move(cement, "out", "2", "50", _nov(5), project_id=pid, requested=True)
        _move(pipe, "out", "3", "10", _nov(5), project_id=pid, requested=True)
        db.session.commit()
        cid, pid_ = cement.id, pipe.id
    window = {"from": "2026-11-01", "to": "2026-11-14"}
    assert [e["name"] for e in _get(admin_client, "in", **window)["report"]["entries"]] == ["Cement", "Pipe"]
    assert [e["name"] for e in _get(admin_client, "in", material_id=pid_, **window)["report"]["entries"]] == ["Pipe"]
    assert [e["name"] for e in _get(admin_client, "out", material_id=cid, **window)["report"]["entries"]] == ["Cement"]
    assert len(_get(admin_client, "out", **window)["report"]["entries"]) == 2
    assert [m["label"].split(" (")[0] for m in _get(admin_client, "in", **window)["materials"]] == ["Cement", "Pipe"]


# ---------- 2. stock out (allocation), day by day ----------

def test_stock_out_is_what_went_to_projects_with_returns_as_minus_rows(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        cement, pipe = _material("Cement"), _material("Pipe", "mtr")
        _move(cement, "out", "10", "50", _nov(4), project_id=pid, requested=True)           # 500
        _move(pipe, "out", "5", "20", _nov(4), project_id=pid, requested=True)              # 100
        _move(cement, "in", "2", "50", _nov(6), project_id=pid, requested=True)             # 2 came back: -100
        _move(cement, "out", "7", "50", _nov(1), project_id=pid, requested=True)            # before the range
        _move(cement, "out", "3", "50", _nov(5), project_id=pid, status="pending", requested=True)
        db.session.commit()
    d = _get(admin_client, "out", **{"from": "2026-11-02", "to": "2026-11-10"})["report"]
    assert [(day["date"], day["total"]) for day in d["days"]] == [("2026-11-04", 600.0), ("2026-11-06", -100.0)]
    assert d["total"] == 500.0 and d["count"] == 3
    back = d["days"][1]["entries"][0]
    assert (back["kind"], back["quantity"], back["amount"], back["name"]) == ("Returned", -2.0, -100.0, "Cement")
    issued = next(e for e in d["days"][0]["entries"] if e["name"] == "Pipe")
    assert (issued["kind"], issued["project_code"], issued["quantity"], issued["amount"]) == ("Issued", "PRJ-0001", 5.0, 100.0) and issued["project"]


# ---------- 3. inventory status on a day ----------

def test_the_status_on_a_day_replays_the_ledger_up_to_it(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        cement, pipe, used = _material("Cement"), _material("Pipe", "mtr"), _material("Used Up")
        _move(cement, "in", "10", "50", _nov(1))                                           # 10 at 50
        _move(cement, "in", "10", "70", _nov(3))                                           # 20 at the blended 60
        _move(cement, "out", "5", "60", _nov(5), project_id=pid, requested=True)           # 15 left
        _move(pipe, "in", "4", "100", _nov(8))
        _move(used, "in", "3", "10", _nov(2))
        _move(used, "out", "3", "10", _nov(4), project_id=pid, requested=True)             # all gone
        db.session.commit()

    def status(day):
        r = _get(admin_client, "status", as_on=day)["report"]
        return {x["name"]: x for x in r["rows"]}, r["total"]

    rows, total = status("2026-11-02")
    assert (rows["Cement"]["quantity"], rows["Cement"]["rate"], rows["Cement"]["value"]) == (10.0, 50.0, 500.0)
    assert (rows["Used Up"]["quantity"], total) == (3.0, 530.0) and "Pipe" not in rows
    rows, total = status("2026-11-04")
    assert (rows["Cement"]["quantity"], rows["Cement"]["rate"], rows["Cement"]["value"]) == (20.0, 60.0, 1200.0)
    assert (rows["Used Up"]["quantity"], rows["Used Up"]["status"]) == (0.0, "Out of stock")
    rows, total = status("2026-11-10")
    assert (rows["Cement"]["quantity"], rows["Cement"]["value"], rows["Pipe"]["value"], total) == (15.0, 900.0, 400.0, 1300.0)
    assert status("2026-10-31") == ({}, 0.0)
    assert [r["name"] for r in _get(admin_client, "status", as_on="2026-11-10")["report"]["rows"]][-1] == "Used Up"     # what ran out is listed last


def test_what_is_short_for_waiting_requests_is_only_shown_for_today(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        short = _material("Short Pipe", "mtr", qty="3", rate="10")
        _move(short, "in", "3", "10", _nov(1))
        _move(short, "out", "10", "10", _nov(2), project_id=pid, status="pending", requested=True)
        db.session.commit()
    today = _get(admin_client, "status")["report"]
    assert [(s["name"], s["in_stock"], s["requested"], s["short_by"]) for s in today["short"]] == [("Short Pipe", 3.0, 10.0, 7.0)]
    assert _get(admin_client, "status", as_on="2026-11-05")["report"]["short"] == []


# ---------- the dates and the material ----------

def test_the_dates_default_to_this_month_so_far_and_today(admin_client):
    d = _get(admin_client, "in")
    today = today_local()
    assert (d["from"], d["to"], d["as_on"]) == (today.replace(day=1).isoformat(), today.isoformat(), today.isoformat())


@pytest.mark.parametrize("query", [
    {"from": "2026-11-10", "to": "2026-11-02"},                                           # from after to
    {"to": (date.today() + timedelta(days=2)).isoformat()},                              # a day that has not happened
    {"as_on": (date.today() + timedelta(days=2)).isoformat()},
    {"from": "soon"}, {"to": "13-11-2026"}, {"as_on": "x"},
    {"from": "2020-01-01", "to": "2026-11-01"},                                           # more than two years
    {"material_id": "99999"},
    {"part": "everything"},
])
def test_a_bad_date_range_material_or_part_is_refused(admin_client, query):
    res = admin_client.get("/api/inventory/report", query_string=query)
    assert res.status_code == 422 and res.get_json()["error"], query


# ---------- the Excel: one sheet for each report ----------

def test_the_excel_has_a_sheet_for_each_report_for_the_dates_and_material_picked(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        cement, pipe = _material("Cement"), _material("Pipe", "mtr")
        _move(cement, "in", "10", "50", _nov(3), gst="18")
        _move(pipe, "in", "20", "10", _nov(3))
        _move(cement, "out", "4", "50", _nov(5), project_id=pid, requested=True)
        _move(pipe, "out", "5", "10", _nov(5), project_id=pid, requested=True)
        db.session.commit()
        cid = cement.id
    res = admin_client.get("/api/reports/inventory", query_string={"from": "2026-11-01", "to": "2026-11-14", "as_on": "2026-11-10"})
    assert res.status_code == 200 and "inventory-report-2026-11-01-to-2026-11-14.xlsx" in res.headers["Content-Disposition"]
    wb = load_workbook(io.BytesIO(res.data))
    assert wb.sheetnames == ["Stock in", "Stock out", "Inventory status"]
    rows = lambda name: [[c.value for c in r] for r in wb[name].iter_rows(min_row=2)]       # noqa: E731
    stock_in = rows("Stock in")
    assert [(r[0], r[1]) for r in stock_in] == [("2026-11-03", "Cement"), ("2026-11-03", "Pipe"), ("Total", None)] and stock_in[-1][8] == 790
    stock_out = rows("Stock out")
    assert [(r[1], r[4], r[7], r[9]) for r in stock_out[:-1]] == [("Issued", "Cement", 4, 200), ("Issued", "Pipe", 5, 50)] and stock_out[-1][9] == 250
    status = rows("Inventory status")
    assert [(r[0], r[4]) for r in status[:-1]] == [("Cement", 6), ("Pipe", 15)] and status[-1][6] == 300 + 150
    only = load_workbook(io.BytesIO(admin_client.get("/api/reports/inventory", query_string={"from": "2026-11-01", "to": "2026-11-14", "material_id": cid}).data))
    assert [r[0].value for r in only["Stock in"].iter_rows(min_row=2)] == ["2026-11-03", "Total"]
    assert admin_client.get("/api/reports/inventory", query_string={"from": "2026-11-10", "to": "2026-11-01"}).status_code == 422


# ---------- where it lives ----------

def test_inventory_is_a_subtab_of_the_reports_page_and_nothing_else_is_left_behind(client, admin_client):
    """kohal, 2026-11-14: "have inventory report as a subtab in reports block in me tab"."""
    reports = admin_client.get("/api/reports").get_json()["reports"]
    assert [r["key"] for r in reports] == ["leads", "payroll", "projects", "inventory", "transactions"]
    assert [r.get("range", False) for r in reports] == [False, False, False, True, True]               # picked by dates, not by month
    res = admin_client.get("/inventory-report")
    assert res.status_code == 302 and res.headers["Location"].endswith("/reports#inventory")      # an old bookmark still lands on it
    page = admin_client.get("/me").data
    assert b"/inventory-report" not in page and b'class="me-tile" href="/inventory"' not in page    # no tile of its own, and no plain Inventory tile
    assert b'href="/inventory"' in page                                                            # the bottom bar's Inventory tab still opens it
    assert b"Reports" in page


def test_only_people_who_can_see_reports_and_inventory_get_the_figures(client, admin_client, accounts_client):
    assert admin_client.get("/api/inventory/report").status_code == 200
    for url in ("/api/inventory/report", "/api/reports/inventory", "/api/reports"):
        assert client.get(url).status_code in (403, 404), url
    assert accounts_client.get("/api/reports/inventory").status_code == 403                     # Reports is the admin's alone

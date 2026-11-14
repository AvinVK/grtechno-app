"""Inventory report (kohal, 2026-11-14: "in me tab in inventory block, i want to see inventory report ... monthly reports of total stock in, stocks
allocated to projects" - plus stock value now, a low-stock list and an Excel download) - see app/inventory_report.py."""

import io
from datetime import date
from decimal import Decimal

from openpyxl import load_workbook

from app.extensions import db
from app.models import Material, MaterialMovement
from test_projects import make_project


def _material(name, unit="bags", qty="0", rate="0", active=True):
    m = Material(name=name, unit=unit, stock_qty=Decimal(qty), avg_rate=Decimal(rate), is_active=active)
    db.session.add(m)
    db.session.flush()
    return m


def _move(material, kind, qty, rate, day, project_id=None, status="approved", gst="0", requested=False):
    amount = Decimal(qty) * Decimal(rate)
    gst_amount = (amount * Decimal(gst) / 100).quantize(Decimal("0.01"))
    db.session.add(MaterialMovement(material=material, kind=kind, quantity=Decimal(qty), rate=Decimal(rate), amount=amount, project_id=project_id,
                                    entry_date=day, status=status, gst_percent=Decimal(gst), gst_amount=gst_amount, total_cost=amount + gst_amount,
                                    requested=requested))


def _report(client, month="2026-11"):
    res = client.get(f"/api/inventory/report?month={month}")
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_stock_in_is_the_months_purchases_per_material_with_gst(app, admin_client):
    with app.app_context():
        cement, pipe = _material("Cement"), _material("Pipe", "mtr")
        _move(cement, "in", "10", "50", date(2026, 11, 3), gst="18")                 # 500 + 90
        _move(cement, "in", "5", "60", date(2026, 11, 20))                           # 300
        _move(pipe, "in", "20", "10", date(2026, 11, 9))                             # 200
        _move(cement, "in", "99", "50", date(2026, 10, 30))                          # another month
        _move(cement, "in", "99", "50", date(2026, 11, 5), status="pending")         # not moved stock yet
        _move(cement, "in", "99", "50", date(2026, 11, 6), status="rejected")
        db.session.commit()
    s = _report(admin_client)["stock_in"]
    rows = {r["name"]: r for r in s["rows"]}
    assert (rows["Cement"]["quantity"], rows["Cement"]["amount"], rows["Cement"]["gst"], rows["Cement"]["total"], rows["Cement"]["entries"]) == (15.0, 800.0, 90.0, 890.0, 2)
    assert (rows["Pipe"]["quantity"], rows["Pipe"]["unit"], rows["Pipe"]["total"]) == (20.0, "mtr", 200.0)
    assert s["total"] == 1090.0 and s["entries"] == 3
    assert _report(admin_client, "2026-10")["stock_in"]["total"] == 4950.0
    assert _report(admin_client, "2026-09")["stock_in"] == {"rows": [], "total": 0.0, "entries": 0}


def test_allocated_to_projects_is_what_went_out_less_what_came_back(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        cement, pipe = _material("Cement"), _material("Pipe", "mtr")
        _move(cement, "out", "10", "50", date(2026, 11, 4), project_id=pid, requested=True)         # 500
        _move(cement, "in", "2", "50", date(2026, 11, 12), project_id=pid, requested=True)          # 2 came back: 100
        _move(pipe, "out", "5", "20", date(2026, 11, 8), project_id=pid, requested=True)            # 100
        _move(cement, "out", "7", "50", date(2026, 10, 28), project_id=pid, requested=True)         # another month
        _move(cement, "out", "3", "50", date(2026, 11, 9), project_id=pid, status="pending", requested=True)
        db.session.commit()
    a = _report(admin_client)["allocated"]
    assert a["total"] == 500.0 and len(a["projects"]) == 1
    p = a["projects"][0]
    assert (p["project_id"], p["amount"]) == (pid, 500.0)
    mats = {m["name"]: m for m in p["materials"]}
    assert (mats["Cement"]["quantity"], mats["Cement"]["amount"]) == (8.0, 400.0) and (mats["Pipe"]["quantity"], mats["Pipe"]["amount"]) == (5.0, 100.0)
    assert _report(admin_client, "2026-10")["allocated"]["total"] == 350.0


def test_a_return_is_not_counted_as_stock_in_and_a_fully_returned_material_drops_off(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        cement = _material("Cement")
        _move(cement, "out", "4", "50", date(2026, 11, 4), project_id=pid, requested=True)
        _move(cement, "in", "4", "50", date(2026, 11, 6), project_id=pid, requested=True)
        db.session.commit()
    r = _report(admin_client)
    assert r["stock_in"]["rows"] == [] and r["allocated"]["projects"] == []


def test_stock_value_now_lists_what_is_in_stock_and_what_it_is_worth(app, admin_client):
    with app.app_context():
        _material("Cement", qty="100", rate="50")
        _material("Pipe", "mtr", qty="10", rate="300")
        _material("Empty", qty="0", rate="40")
        _material("Retired", qty="5", rate="10", active=False)
        db.session.commit()
    s = _report(admin_client)["stock"]
    assert [(r["name"], r["quantity"], r["rate"], r["value"]) for r in s["rows"]] == [("Cement", 100.0, 50.0, 5000.0), ("Pipe", 10.0, 300.0, 3000.0)]
    assert s["total"] == 8000.0


def test_low_stock_has_the_materials_that_cannot_cover_requests_and_ones_that_ran_out(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        short = _material("Short Pipe", "mtr", qty="3", rate="10")
        gone = _material("Used Up", qty="0", rate="10")
        _material("Never Stocked")                                                        # never had any: not "ran out"
        _move(gone, "in", "5", "10", date(2026, 11, 1))
        _move(short, "out", "10", "10", date(2026, 11, 2), project_id=pid, status="pending", requested=True)
        db.session.commit()
    low = _report(admin_client)["low"]
    assert [(r["name"], r["in_stock"], r["requested"], r["short_by"]) for r in low["short"]] == [("Short Pipe", 3.0, 10.0, 7.0)]
    assert [r["name"] for r in low["out"]] == ["Used Up"]


def test_the_month_defaults_to_this_one_and_must_be_a_real_month(admin_client):
    r = _report(admin_client, "")
    assert len(r["months"]) == 24 and r["month"] == r["current"] == r["months"][0]["value"]
    assert admin_client.get("/api/inventory/report?month=soon").status_code == 422


def test_the_excel_has_a_sheet_for_each_part(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        cement = _material("Cement", qty="20", rate="50")
        _move(cement, "in", "10", "50", date(2026, 11, 3), gst="18")
        _move(cement, "out", "4", "50", date(2026, 11, 5), project_id=pid, requested=True)
        db.session.commit()
    res = admin_client.get("/api/inventory/report.xlsx?month=2026-11")
    assert res.status_code == 200 and "inventory-report-2026-11.xlsx" in res.headers["Content-Disposition"]
    wb = load_workbook(io.BytesIO(res.data))
    assert wb.sheetnames == ["Summary", "Stock in", "Allocated to projects", "Stock now", "Low stock"]
    stock_in = [[c.value for c in r] for r in wb["Stock in"].iter_rows(min_row=2)]
    assert stock_in == [["Cement", stock_in[0][1], "bags", 10, 500, 90, 590, 1]]
    allocated = [[c.value for c in r] for r in wb["Allocated to projects"].iter_rows(min_row=2)]
    assert [(r[2], r[4], r[5]) for r in allocated] == [("Cement", 4, 200)]
    assert [[c.value for c in r][5] for r in wb["Stock now"].iter_rows(min_row=2)] == [1000]
    assert admin_client.get("/api/inventory/report.xlsx?month=bad").status_code == 422


def test_only_people_with_the_inventory_module_see_the_report_and_its_tile(client, admin_client, accounts_client):
    assert admin_client.get("/inventory-report").status_code == 200
    assert b"Inventory report" in admin_client.get("/me").data
    for url in ("/inventory-report", "/api/inventory/report", "/api/inventory/report.xlsx"):
        assert client.get(url).status_code in (403, 404), url
    assert b"/inventory-report" not in client.get("/me").data


def test_the_me_tab_has_the_report_tile_and_no_plain_inventory_tile(admin_client):
    page = admin_client.get("/me").data
    assert b'class="me-tile" href="/inventory-report"' in page
    assert b'class="me-tile" href="/inventory"' not in page
    assert b'href="/inventory"' in page                                     # the bottom bar's Inventory tab still opens it

"""Pay allowances (kohal, 2026-11-11: "add allowance as well. have a note in deduction, advance and allowance to specify which allowance it
is and also adjust this in payroll sheet") - an amount, and a note saying which allowance, added to one month / one 2-week pay period."""

import io
from datetime import date
from decimal import Decimal

from openpyxl import load_workbook

from app.advances import add_months, prev_slot, slot_start_of
from app.extensions import db
from app.models import PayAllowance, PayDeduction, Worker, WorkerAttendance
from app.timeutil import today_local
from tests.conftest import make_user, signed_in


def _worker(app, name="Ravi", kind="regular", wage="30000"):
    with app.app_context():
        w = Worker(name=name, category="manpower", employment_type=kind, wage_amount=Decimal(wage))
        db.session.add(w)
        db.session.commit()
        return w.id


def _month(offset=0):
    d = add_months(today_local().replace(day=1), offset)
    return f"{d.year}-{d.month:02d}"


def _give(client, wid, amount="500", period=None, note="Travel allowance", **extra):
    body = {"worker_id": wid, "amount": amount, "note": note, **extra}
    if period is not None:
        body["period"] = period
    return client.post("/api/payroll/allowances", json=body)


def _row(client, wid):
    return [e for e in client.get("/api/payroll/overview").get_json()["employees"] if e["id"] == wid]


def test_an_allowance_is_added_to_a_salaried_employees_due_from_its_month_on(app, admin_client):
    wid = _worker(app)
    before = _row(admin_client, wid)[0]
    assert _give(admin_client, wid, "700", _month(1)).status_code == 201                  # next month: nothing added yet
    assert _row(admin_client, wid)[0]["other_allowance"] == 0.0 and _row(admin_client, wid)[0]["outstanding"] == before["outstanding"]
    a = _give(admin_client, wid, "300.50", _month(0), note="Mobile").get_json()["allowance"]
    assert (a["amount"], a["note"], a["applied"], a["period"]) == (300.5, "Mobile", True, _month(0))
    after = _row(admin_client, wid)[0]
    assert after["other_allowance"] == 300.5 and after["outstanding"] == round(before["outstanding"] + 300.5, 2)


def test_a_daily_wage_allowance_goes_on_its_own_pay_period(app, admin_client):
    wid = _worker(app, "Sita", "daily_wages", "500")
    slot = slot_start_of(today_local())
    before = {r["period_start"]: r["outstanding"] for r in _row(admin_client, wid)}
    r = _give(admin_client, wid, "200", slot.isoformat(), note="Fuel")
    assert r.status_code == 201 and r.get_json()["allowance"]["period"] == slot.isoformat()
    rows = {r["period_start"]: r for r in _row(admin_client, wid)}
    assert rows[slot.isoformat()]["other_allowance"] == 200.0
    assert rows[slot.isoformat()]["outstanding"] == round(before[slot.isoformat()] + 200, 2)
    assert all(r["other_allowance"] == 0.0 for key, r in rows.items() if key != slot.isoformat())


def test_an_allowance_a_deduction_and_an_advance_all_count(app, admin_client):
    wid = _worker(app)
    before = _row(admin_client, wid)[0]
    admin_client.post("/api/payroll/advances", json={"worker_id": wid, "amount": "8000", "months": 4, "first_month": _month(0), "payment_account": "CASH"})
    admin_client.post("/api/payroll/deductions", json={"worker_id": wid, "amount": "100", "period": _month(0), "reason": "Late"})
    _give(admin_client, wid, "350", _month(0))
    row = _row(admin_client, wid)[0]
    assert (row["advance_deduction"], row["other_deduction"], row["other_allowance"]) == (2000.0, 100.0, 350.0)
    assert row["outstanding"] == round(before["outstanding"] - 2000 - 100 + 350, 2)


def test_the_list_offers_the_same_periods_as_a_deduction(app, admin_client):
    salaried = _worker(app)
    daily = _worker(app, "Sita", "daily_wages", "500")
    for wid in (salaried, daily):
        a = admin_client.get(f"/api/payroll/allowances?worker_id={wid}").get_json()
        d = admin_client.get(f"/api/payroll/deductions?worker_id={wid}").get_json()
        assert a["periods"] == d["periods"] and a["current_period"] == d["current_period"] and a["unit"] == d["unit"]
    _give(admin_client, salaried, "100", _month(0))
    data = admin_client.get(f"/api/payroll/allowances?worker_id={salaried}").get_json()
    assert [(x["amount"], x["note"]) for x in data["allowances"]] == [(100.0, "Travel allowance")]


def test_what_cannot_be_given_is_refused_and_nothing_is_saved(app, admin_client):
    wid = _worker(app)
    daily = _worker(app, "Sita", "daily_wages", "500")
    nowage = _worker(app, "No Wage")
    with app.app_context():
        db.session.get(Worker, nowage).wage_amount = None
        db.session.commit()
    assert _give(admin_client, nowage).status_code == 422
    for kw, field in (({"amount": "0"}, "amount"), ({"amount": "abc"}, "amount"), ({"note": "  "}, "note"), ({"note": "x" * 301}, "note"),
                      ({"period": _month(-1)}, "period"), ({"period": _month(12)}, "period"), ({"period": "soon"}, "period")):
        r = _give(admin_client, wid, **kw)
        assert r.status_code == 422 and field in r.get_json()["fields"], kw
    slot = slot_start_of(today_local())
    for period in ("2026-11-05", "2020-01-01", prev_slot(prev_slot(prev_slot(prev_slot(prev_slot(slot))))).isoformat()):
        assert "period" in _give(admin_client, daily, period=period).get_json()["fields"], period
    assert _give(admin_client, 99999).status_code == 404
    with app.app_context():
        assert PayAllowance.query.count() == 0


def test_the_admin_can_remove_one_and_the_pay_goes_back_down(app, admin_client):
    wid = _worker(app)
    before = _row(admin_client, wid)[0]["outstanding"]
    a = _give(admin_client, wid, "400", _month(0)).get_json()["allowance"]
    assert _row(admin_client, wid)[0]["outstanding"] == round(before + 400, 2)
    assert admin_client.delete(f"/api/payroll/allowances/{a['id']}").status_code == 200
    assert _row(admin_client, wid)[0]["outstanding"] == before
    assert admin_client.delete(f"/api/payroll/allowances/{a['id']}").status_code == 404


def test_only_the_admin_gives_sees_or_removes_allowances(app, admin_client, client, accounts_client, manager_client):
    wid = _worker(app)
    a = _give(admin_client, wid, "100", _month(0)).get_json()["allowance"]
    for c in (client, accounts_client, manager_client):
        assert _give(c, wid).status_code in (403, 404)
        assert c.get(f"/api/payroll/allowances?worker_id={wid}").status_code in (403, 404)
        assert c.delete(f"/api/payroll/allowances/{a['id']}").status_code in (403, 404)
    with app.app_context():
        assert PayAllowance.query.count() == 1


# ---------- the payment sheets and the slip ----------

def _salaried(name, salary, allowance=None, deduction=None):
    w = Worker(name=name, category="staff", employment_type="regular", wage_amount=Decimal(salary))
    db.session.add(w)
    db.session.flush()
    for day in range(1, 32):
        if date(2026, 10, day).weekday() != 6:
            db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
    if allowance:
        db.session.add(PayAllowance(worker=w, amount=Decimal(allowance), period_start=date(2026, 10, 1), note="Travel"))
    if deduction:
        db.session.add(PayDeduction(worker=w, amount=Decimal(deduction), period_start=date(2026, 10, 1), reason="Late"))
    return w


def _pusher():
    p = Worker(name="Zed Pusher", category="manpower")
    db.session.add(p)
    db.session.flush()
    db.session.add(WorkerAttendance(worker=p, work_date=date(2026, 11, 1)))


def test_the_salaried_sheet_adds_the_allowance_to_the_gross(app, admin_client):
    with app.app_context():
        _salaried("Ankush", "31000", allowance="2000", deduction="500")
        _salaried("Rashmi", "31000")
        _pusher()
        db.session.commit()
    data = admin_client.get("/api/payroll/sheet?month=2026-10").get_json()
    rows = {r["name"]: r for r in data["rows"]}
    assert (rows["Ankush"]["other_allowance"], rows["Ankush"]["gross"], rows["Ankush"]["salary_due"]) == (2000, 32500, 32500)   # 31000 + 2000 - 500
    assert (rows["Ankush"]["other_allowance_note"], rows["Ankush"]["other_deduction_note"]) == ("Travel", "Late")
    assert rows["Rashmi"]["other_allowance"] == 0 and rows["Rashmi"]["gross"] == 31000
    assert data["totals"]["other_allowance"] == 2000 and data["totals"]["gross"] == 32500 + 31000
    nov = admin_client.get("/api/payroll/sheet?month=2026-11").get_json()
    assert all(r["other_allowance"] == 0 for r in nov["rows"])                              # it was for October only


def test_the_sheet_excel_has_an_other_allowance_column(app, admin_client):
    with app.app_context():
        _salaried("Ankush", "31000", allowance="2000")
        _pusher()
        db.session.commit()
    ws = load_workbook(io.BytesIO(admin_client.get("/api/payroll/sheet.xlsx?month=2026-10").data)).active
    cells = [[c.value for c in row] for row in ws.iter_rows()]
    col = cells[1].index("Other allowance")
    assert cells[1][col - 1] == "House rent / petrol" and cells[3][col] == 2000 and cells[3][cells[1].index("Gross salary")] == 33000


def test_the_daily_sheet_adds_the_allowance_to_the_net_payable(app, admin_client):
    with app.app_context():
        w = Worker(name="Gita", category="manpower", employment_type="contractor", wage_amount=Decimal("500"))
        db.session.add(w)
        db.session.flush()
        for day in (1, 2, 3, 6):                                                              # 4 days = 2,000
            db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
        db.session.add(PayAllowance(worker=w, amount=Decimal("300"), period_start=date(2026, 10, 1), note="Fuel"))
        db.session.add(PayDeduction(worker=w, amount=Decimal("100"), period_start=date(2026, 10, 1), reason="Damage"))
        _pusher()
        db.session.commit()
    row = next(r for r in admin_client.get("/api/payroll/sheet/daily?period=2026-10-01").get_json()["rows"] if r["name"] == "Gita")
    assert (row["earned"], row["other_allowance"], row["other_deduction"], row["net"], row["due"]) == (2000, 300, 100, 2200, 2200)
    ws = load_workbook(io.BytesIO(admin_client.get("/api/payroll/sheet/daily.xlsx?period=2026-10-01").data)).active
    header = [c.value for c in ws[2]]
    assert header[header.index("Wages earned") + 1] == "Other allowance"


def test_the_slip_shows_the_allowance_and_which_one_it_is(app, admin_client):
    with app.app_context():
        user = make_user("Ritesh")
        w = _salaried("Ritesh", "31000", allowance="2000", deduction="500")
        w.user_code = user.code
        _pusher()
        db.session.commit()
        wid = w.id
        employee = signed_in(app, user)
    assert admin_client.post("/api/payroll/slips", json={"kind": "salaried", "period": "2026-10", "worker_id": wid}).status_code == 201
    listed = employee.get("/api/salary-slips").get_json()["slips"]
    assert listed[0]["net"] == 32500
    view = employee.get(f"/api/salary-slips/{listed[0]['id']}").get_json()["slip"]
    rows = {row["label"]: row["value"] for s in view["sections"] for row in s["rows"]}
    assert rows["Other allowance (Travel)"] == 2000 and rows["Other deduction (Late)"] == 500
    pdf = employee.get(f"/api/salary-slips/{listed[0]['id']}.pdf").data
    assert b"Other allowance \\(Travel\\)" in pdf and b"Rs. 32,500" in pdf


def test_an_adjustment_on_last_months_daily_period_shows_in_that_periods_sheet(app, admin_client):
    """kohal, 2026-11-12: the daily-wage picker offers last month's periods - the payment sheet for that period must carry them."""
    wid = _worker(app, "Gita", "daily_wages", "500")
    current = slot_start_of(today_local())
    older = prev_slot(prev_slot(current))                                                 # one of last month's periods
    assert older.isoformat() in [p["value"] for p in admin_client.get(f"/api/payroll/allowances?worker_id={wid}").get_json()["periods"]]

    def sheet_row(period):
        rows = admin_client.get(f"/api/payroll/sheet/daily?period={period.isoformat()}").get_json()["rows"]
        return next(r for r in rows if r["id"] == wid)

    before = sheet_row(older)
    assert _give(admin_client, wid, "300", older.isoformat(), note="Fuel").status_code == 201
    assert admin_client.post("/api/payroll/deductions", json={"worker_id": wid, "amount": "100", "period": older.isoformat(), "reason": "Damage"}).status_code == 201
    row = sheet_row(older)
    assert (row["other_allowance"], row["other_deduction"]) == (300, 100)
    assert (row["other_allowance_note"], row["other_deduction_note"]) == ("Fuel", "Damage")
    assert row["net"] == round(before["net"] + 300 - 100, 2) and row["due"] == round(before["due"] + 200, 2)
    other = sheet_row(current)
    assert (other["other_allowance"], other["other_deduction"]) == (0, 0)                  # only that period
    ws = load_workbook(io.BytesIO(admin_client.get(f"/api/payroll/sheet/daily.xlsx?period={older.isoformat()}").data)).active
    header = [c.value for c in ws[2]]
    mine = next(r for r in ws.iter_rows(min_row=3, values_only=True) if r[header.index("Name")] == "Gita")
    assert mine[header.index("Other allowance")] == 300 and mine[header.index("Other deduction")] == 100

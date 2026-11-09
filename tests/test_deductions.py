"""Pay deductions (kohal, 2026-11-09: "give deduction subtab below give advance. this deduction should be taken into consideration when
calculating salary for salaried or daily wages") - an amount and a reason put against one month / one 2-week pay period."""

import io
from datetime import date
from decimal import Decimal

from openpyxl import load_workbook

from app.advances import add_months, add_slots, next_slot, slot_start_of
from app.extensions import db
from app.models import PayDeduction, Worker, WorkerAttendance
from app.timeutil import today_local


def _worker(app, name="Ravi", kind="regular", wage="30000"):
    with app.app_context():
        w = Worker(name=name, category="manpower", employment_type=kind, wage_amount=Decimal(wage))
        db.session.add(w)
        db.session.commit()
        return w.id


def _month(offset=0):
    d = add_months(today_local().replace(day=1), offset)
    return f"{d.year}-{d.month:02d}"


def _give(client, wid, amount="500", period=None, reason="Damaged equipment", **extra):
    body = {"worker_id": wid, "amount": amount, "reason": reason, **extra}
    if period is not None:
        body["period"] = period
    return client.post("/api/payroll/deductions", json=body)


def _row(client, wid):
    return [e for e in client.get("/api/payroll/overview").get_json()["employees"] if e["id"] == wid]


def test_a_deduction_comes_off_a_salaried_employees_due_from_its_month_on(app, admin_client):
    wid = _worker(app)
    before = _row(admin_client, wid)[0]
    r = _give(admin_client, wid, "700", _month(1))                              # next month: nothing comes off yet
    assert r.status_code == 201
    assert _row(admin_client, wid)[0]["other_deduction"] == 0.0 and _row(admin_client, wid)[0]["outstanding"] == before["outstanding"]
    d = _give(admin_client, wid, "300.50", _month(0), reason="Fine").get_json()["deduction"]
    assert (d["amount"], d["reason"], d["applied"], d["period"]) == (300.5, "Fine", True, _month(0))
    after = _row(admin_client, wid)[0]
    assert after["other_deduction"] == 300.5 and after["outstanding"] == round(before["outstanding"] - 300.5, 2)


def test_a_daily_wage_deduction_comes_off_only_its_own_pay_period(app, admin_client):
    wid = _worker(app, "Sita", "daily_wages", "500")
    slot = slot_start_of(today_local())
    before = {r["period_start"]: r["outstanding"] for r in _row(admin_client, wid)}
    r = _give(admin_client, wid, "200", slot.isoformat())
    assert r.status_code == 201 and r.get_json()["deduction"]["period"] == slot.isoformat()
    rows = {r["period_start"]: r for r in _row(admin_client, wid)}
    assert rows[slot.isoformat()]["other_deduction"] == 200.0
    assert rows[slot.isoformat()]["outstanding"] == round(before[slot.isoformat()] - 200, 2)
    others = [r for key, r in rows.items() if key != slot.isoformat()]
    assert all(r["other_deduction"] == 0.0 for r in others)


def test_an_advance_and_a_deduction_both_come_off(app, admin_client):
    wid = _worker(app)
    before = _row(admin_client, wid)[0]
    admin_client.post("/api/payroll/advances", json={"worker_id": wid, "amount": "8000", "months": 4, "first_month": _month(0), "payment_account": "CASH"})
    _give(admin_client, wid, "100", _month(0))
    row = _row(admin_client, wid)[0]
    assert (row["advance_deduction"], row["other_deduction"]) == (2000.0, 100.0)
    assert row["outstanding"] == round(before["outstanding"] - 2100, 2)


def test_the_list_shows_each_deduction_and_the_periods_it_can_be_put_against(app, admin_client):
    salaried = _worker(app)
    daily = _worker(app, "Sita", "daily_wages", "500")
    _give(admin_client, salaried, "100", _month(0))
    data = admin_client.get(f"/api/payroll/deductions?worker_id={salaried}").get_json()
    assert data["unit"] == "month" and data["current_period"] == _month(0) and data["periods"][0]["value"] == _month(0)
    assert len(data["periods"]) == 12 and [d["amount"] for d in data["deductions"]] == [100.0]
    slot = slot_start_of(today_local())
    data = admin_client.get(f"/api/payroll/deductions?worker_id={daily}").get_json()
    assert data["unit"] == "fortnight" and data["current_period"] == slot.isoformat()
    assert [p["value"] for p in data["periods"][:3]] == [add_slots(slot, i).isoformat() for i in range(3)] and len(data["periods"]) == 24


def test_what_cannot_be_given_is_refused_and_nothing_is_saved(app, admin_client):
    wid = _worker(app)
    daily = _worker(app, "Sita", "daily_wages", "500")
    nowage = _worker(app, "No Wage")
    with app.app_context():
        db.session.get(Worker, nowage).wage_amount = None
        db.session.commit()
    assert _give(admin_client, nowage).status_code == 422
    for kw, field in (({"amount": "0"}, "amount"), ({"amount": "abc"}, "amount"), ({"reason": "  "}, "reason"), ({"reason": "x" * 301}, "reason"),
                      ({"period": _month(-1)}, "period"), ({"period": _month(12)}, "period"), ({"period": "soon"}, "period")):
        r = _give(admin_client, wid, **kw)
        assert r.status_code == 422 and field in r.get_json()["fields"], kw
    for period in ("2026-11-05", "2020-01-01", add_slots(slot_start_of(today_local()), 24).isoformat()):
        assert "period" in _give(admin_client, daily, period=period).get_json()["fields"], period
    assert _give(admin_client, 99999).status_code == 404
    with app.app_context():
        assert PayDeduction.query.count() == 0


def test_the_admin_can_remove_one_and_the_pay_goes_back_up(app, admin_client):
    wid = _worker(app)
    before = _row(admin_client, wid)[0]["outstanding"]
    d = _give(admin_client, wid, "400", _month(0)).get_json()["deduction"]
    assert _row(admin_client, wid)[0]["outstanding"] == round(before - 400, 2)
    assert admin_client.delete(f"/api/payroll/deductions/{d['id']}").status_code == 200
    assert _row(admin_client, wid)[0]["outstanding"] == before
    assert admin_client.delete(f"/api/payroll/deductions/{d['id']}").status_code == 404


def test_only_the_admin_gives_sees_or_removes_deductions(app, admin_client, client, accounts_client, manager_client):
    wid = _worker(app)
    d = _give(admin_client, wid, "100", _month(0)).get_json()["deduction"]
    for c in (client, accounts_client, manager_client):
        assert _give(c, wid).status_code in (403, 404)
        assert c.get(f"/api/payroll/deductions?worker_id={wid}").status_code in (403, 404)
        assert c.delete(f"/api/payroll/deductions/{d['id']}").status_code in (403, 404)
    with app.app_context():
        assert PayDeduction.query.count() == 1


# ---------- the payment sheets ----------

def _salaried(name, salary, deduction=None):
    w = Worker(name=name, category="staff", employment_type="regular", wage_amount=Decimal(salary))
    db.session.add(w)
    db.session.flush()
    for day in range(1, 32):
        if date(2026, 10, day).weekday() != 6:
            db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
    if deduction:
        db.session.add(PayDeduction(worker=w, amount=Decimal(deduction), period_start=date(2026, 10, 1), reason="Late"))
    return w


def _pusher():
    p = Worker(name="Zed Pusher", category="manpower")
    db.session.add(p)
    db.session.flush()
    db.session.add(WorkerAttendance(worker=p, work_date=date(2026, 11, 1)))


def test_the_salaried_sheet_takes_the_deduction_off_the_gross_and_the_salary_due(app, admin_client):
    with app.app_context():
        _salaried("Ankush", "31000", deduction="1500")
        _salaried("Rashmi", "31000")
        _pusher()
        db.session.commit()
    data = admin_client.get("/api/payroll/sheet?month=2026-10").get_json()
    rows = {r["name"]: r for r in data["rows"]}
    assert (rows["Ankush"]["other_deduction"], rows["Ankush"]["gross"], rows["Ankush"]["salary_due"]) == (1500, 29500, 29500)
    assert (rows["Rashmi"]["other_deduction"], rows["Rashmi"]["gross"]) == (0, 31000)
    assert data["totals"]["other_deduction"] == 1500 and data["totals"]["gross"] == 29500 + 31000
    nov = admin_client.get("/api/payroll/sheet?month=2026-11").get_json()
    assert all(r["other_deduction"] == 0 for r in nov["rows"])                          # it was put against October only


def test_the_salaried_excel_has_an_other_deduction_column(app, admin_client):
    with app.app_context():
        _salaried("Ankush", "31000", deduction="1500")
        _pusher()
        db.session.commit()
    res = admin_client.get("/api/payroll/sheet.xlsx?month=2026-10")
    cells = [[c.value for c in row] for row in load_workbook(io.BytesIO(res.data)).active.iter_rows()]
    header = [h for h in cells[1] if h]
    assert header.index("Other deduction") == header.index("Advance balance") + 1
    col = cells[1].index("Other deduction")
    assert cells[3][col] == 1500 and cells[3][cells[1].index("Gross salary")] == 29500


def test_the_daily_sheet_takes_the_deduction_off_the_net_payable(app, admin_client):
    with app.app_context():
        w = Worker(name="Gita", category="manpower", employment_type="contractor", wage_amount=Decimal("500"))
        db.session.add(w)
        db.session.flush()
        for day in (1, 2, 3, 6):                                                      # 4 days = 2,000
            db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
        db.session.add(PayDeduction(worker=w, amount=Decimal("350"), period_start=date(2026, 10, 1), reason="Damage"))
        _pusher()
        db.session.commit()
    data = admin_client.get("/api/payroll/sheet/daily?period=2026-10-01").get_json()
    row = next(r for r in data["rows"] if r["name"] == "Gita")
    assert (row["earned"], row["other_deduction"], row["net"], row["due"]) == (2000, 350, 1650, 1650)
    assert data["totals"]["other_deduction"] == 350
    second = next(r for r in admin_client.get("/api/payroll/sheet/daily?period=2026-10-16").get_json()["rows"] if r["name"] == "Gita")
    assert second["other_deduction"] == 0
    res = admin_client.get("/api/payroll/sheet/daily.xlsx?period=2026-10-01")
    cells = [[c.value for c in r] for r in load_workbook(io.BytesIO(res.data)).active.iter_rows()]
    assert cells[1].index("Other deduction") == cells[1].index("Advance balance") + 1

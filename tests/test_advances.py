"""Advance salary (kohal, 2026-11-06) - money given ahead of pay, taken back in equal parts across the months that follow."""

from datetime import date
from decimal import Decimal

from app.advances import add_months, add_slots, deducted_before_slot, instalments, next_slot, slot_deduction, slot_start_of
from app.extensions import db
from app.models import SalaryAdvance, Worker
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


def _give(client, wid, amount="20000", months=4, first=None, account="CASH", **extra):
    return client.post("/api/payroll/advances", json={"worker_id": wid, "amount": amount, "months": months,
                                                       "first_month": first or _month(1), "payment_account": account, **extra})


def _row(client, wid):
    return [e for e in client.get("/api/payroll/overview").get_json()["employees"] if e["id"] == wid]


def test_an_advance_is_split_evenly_over_the_chosen_months(app, admin_client):
    wid = _worker(app)
    r = _give(admin_client, wid, "20000", 4, note="Wedding")
    assert r.status_code == 201
    adv = r.get_json()["advance"]
    assert (adv["amount"], adv["months"], adv["monthly"]) == (20000.0, 4, 5000.0)
    assert [i["amount"] for i in adv["instalments"]] == [5000.0] * 4
    assert [i["month"] for i in adv["instalments"]] == [_month(1), _month(2), _month(3), _month(4)]      # "next 4 months"
    assert adv["deducted"] == 0.0 and adv["remaining"] == 20000.0 and adv["note"] == "Wedding"


def test_the_last_instalment_takes_the_leftover_paise(app, admin_client):
    wid = _worker(app)
    adv = _give(admin_client, wid, "10000", 3).get_json()["advance"]
    assert [i["amount"] for i in adv["instalments"]] == [3333.33, 3333.33, 3333.34]
    assert round(sum(i["amount"] for i in adv["instalments"]), 2) == 10000.0


def test_it_starts_when_the_admin_says_and_this_month_counts_as_deducted(app, admin_client):
    wid = _worker(app)
    adv = _give(admin_client, wid, "9000", 3, first=_month(0)).get_json()["advance"]
    assert [i["status"] for i in adv["instalments"]] == ["this month", "upcoming", "upcoming"]
    assert adv["deducted"] == 3000.0 and adv["remaining"] == 6000.0


def test_a_salaried_employees_due_comes_down_by_the_instalments_so_far(app, admin_client):
    wid = _worker(app)
    before = _row(admin_client, wid)[0]
    _give(admin_client, wid, "20000", 4, first=_month(1))                      # starts next month: nothing comes off yet
    assert _row(admin_client, wid)[0]["advance_deduction"] == 0.0
    assert _row(admin_client, wid)[0]["outstanding"] == before["outstanding"]
    _give(admin_client, wid, "8000", 4, first=_month(0))                       # starts this month: 2,000 comes off now
    after = _row(admin_client, wid)[0]
    assert after["advance_deduction"] == 2000.0 and after["outstanding"] == round(before["outstanding"] - 2000, 2)


def test_an_advance_given_before_pay_periods_existed_keeps_splitting_its_month_across_the_two_periods(app):
    """Daily-wage advances given earlier are monthly (unit "month") - they must keep working exactly as they did."""
    with app.app_context():
        w = Worker(name="Sita", category="manpower", employment_type="daily_wages", wage_amount=Decimal("500"))
        db.session.add(w)
        db.session.flush()
        db.session.add(SalaryAdvance(worker=w, amount=Decimal("10000"), months=4, first_month=date(2026, 11, 1),
                                     given_date=date(2026, 11, 2), payment_account="CASH"))      # 2,500 a month
        db.session.add(SalaryAdvance(worker=w, amount=Decimal("5"), months=1, first_month=date(2026, 11, 1),
                                     given_date=date(2026, 11, 2), payment_account="CASH"))      # an odd 5 rupees
        db.session.commit()
        assert [slot_deduction(w, date(2026, 11, 1)), slot_deduction(w, date(2026, 11, 16))] == [Decimal("1252.50"), Decimal("1252.50")]
        assert deducted_before_slot(w, date(2026, 11, 16)) == Decimal("1252.50")
        assert deducted_before_slot(w, date(2026, 12, 1)) == Decimal("2505.00")


# ---------- 2-week pay periods for daily wages (kohal, 2026-11-09: "need 2 week advance deduction and not one month") ----------

def _fortnight(client, wid, amount="10000", periods=4, first=None, account="CASH", **extra):
    first = first or next_slot(slot_start_of(today_local())).isoformat()
    return client.post("/api/payroll/advances", json={"worker_id": wid, "amount": amount, "periods": periods, "first_period": first,
                                                       "payment_account": account, **extra})


def test_pay_periods_step_1st_then_16th_then_the_next_months_1st():
    assert next_slot(date(2026, 11, 1)) == date(2026, 11, 16)
    assert next_slot(date(2026, 11, 16)) == date(2026, 12, 1)
    assert next_slot(date(2026, 12, 16)) == date(2027, 1, 1)
    assert add_slots(date(2026, 11, 16), 3) == date(2027, 1, 1)
    assert slot_start_of(date(2026, 11, 15)) == date(2026, 11, 1) and slot_start_of(date(2026, 11, 16)) == date(2026, 11, 16)


def test_a_daily_wage_advance_is_taken_back_per_two_week_pay_period(app, admin_client):
    wid = _worker(app, "Sita", "daily_wages", "500")
    r = _fortnight(admin_client, wid, "10000", 4, note="Wedding")
    assert r.status_code == 201
    adv = r.get_json()["advance"]
    assert (adv["unit"], adv["months"], adv["part"]) == ("fortnight", 4, 2500.0)
    first = next_slot(slot_start_of(today_local()))
    assert [i["month"] for i in adv["instalments"]] == [add_slots(first, i).isoformat() for i in range(4)]
    assert [i["amount"] for i in adv["instalments"]] == [2500.0] * 4          # 2,500 a pay period, not 5,000 a month
    assert adv["deducted"] == 0.0 and adv["remaining"] == 10000.0
    assert admin_client.get(f"/api/payroll/advances?worker_id={wid}").get_json()["unit"] == "fortnight"


def test_this_pay_period_counts_as_deducted_and_comes_off_that_periods_due(app, admin_client):
    wid = _worker(app, "Sita", "daily_wages", "500")
    slot = slot_start_of(today_local())
    before = {r["period_start"]: r["outstanding"] for r in _row(admin_client, wid)}
    adv = _fortnight(admin_client, wid, "9000", 3, first=slot.isoformat()).get_json()["advance"]
    assert [i["status"] for i in adv["instalments"]] == ["this period", "upcoming", "upcoming"]
    assert adv["deducted"] == 3000.0 and adv["remaining"] == 6000.0
    rows = {r["period_start"]: r for r in _row(admin_client, wid)}
    assert rows[slot.isoformat()]["advance_deduction"] == 3000.0
    assert rows[slot.isoformat()]["outstanding"] == round(before[slot.isoformat()] - 3000, 2)
    if slot.day == 16:
        assert rows[slot.replace(day=1).isoformat()]["advance_deduction"] == 0.0                # the earlier period is untouched


def test_each_pay_period_takes_only_its_own_part(app):
    with app.app_context():
        w = Worker(name="Gita", category="manpower", employment_type="contractor", wage_amount=Decimal("500"))
        db.session.add(w)
        db.session.flush()
        db.session.add(SalaryAdvance(worker=w, amount=Decimal("3000"), months=3, unit="fortnight", first_month=date(2026, 10, 16),
                                     given_date=date(2026, 10, 5), payment_account="CASH"))
        db.session.commit()
        assert [slot_deduction(w, d) for d in (date(2026, 10, 1), date(2026, 10, 16), date(2026, 11, 1), date(2026, 11, 16), date(2026, 12, 1))] == [
            0, 1000, 1000, 1000, 0]
        assert [deducted_before_slot(w, d) for d in (date(2026, 10, 16), date(2026, 11, 1), date(2026, 11, 16), date(2026, 12, 1))] == [
            0, 1000, 2000, 3000]


def test_what_cannot_be_given_to_a_daily_wage_employee_is_refused(app, admin_client):
    wid = _worker(app, "Sita", "daily_wages", "500")
    slot = slot_start_of(today_local())
    past = date(2020, 1, 1)
    for kw, field in (({"periods": 0}, "periods"), ({"periods": 49}, "periods"), ({"first": "2026-11-05"}, "first_period"),
                      ({"first": past.isoformat()}, "first_period"), ({"first": "nonsense"}, "first_period"),
                      ({"amount": "0"}, "amount"), ({"account": "Piggy bank"}, "payment_account")):
        r = _fortnight(admin_client, wid, **kw)
        assert r.status_code == 422 and field in r.get_json()["fields"], kw
    # months do not apply to them, and pay periods do not apply to a salaried employee
    assert "periods" in admin_client.post("/api/payroll/advances", json={"worker_id": wid, "amount": "100", "months": 3, "payment_account": "CASH"}).get_json()["fields"]
    salaried = _worker(app)
    assert "months" in _fortnight(admin_client, salaried).get_json()["fields"]
    with app.app_context():
        assert SalaryAdvance.query.count() == 0


def test_the_ledger_says_pay_periods_for_a_daily_wage_advance(app, admin_client):
    wid = _worker(app, "Sita", "daily_wages", "500")
    _fortnight(admin_client, wid, "10000", 4, account="YES BANK")
    entry = admin_client.get("/api/accounts/detail", query_string={"name": "YES BANK"}).get_json()["entries"][0]
    assert "4 pay periods" in str(entry)


def test_the_advance_is_a_debit_on_the_account_it_was_paid_from(app, admin_client):
    wid = _worker(app)
    _give(admin_client, wid, "20000", 4, account="YES BANK")
    detail = admin_client.get("/api/accounts/detail", query_string={"name": "YES BANK"}).get_json()
    assert [(r["kind"], r["amount"], r["reason"], r["party"]) for r in detail["entries"]] == [("debit", 20000.0, "Salary advance", "Ravi")]


def test_what_cannot_be_given_is_refused_and_nothing_is_saved(app, admin_client):
    wid = _worker(app)
    nowage = _worker(app, "No Wage")
    with app.app_context():
        db.session.get(Worker, nowage).wage_amount = None
        db.session.commit()
    assert _give(admin_client, nowage).status_code == 422                       # nothing to take it back from
    for kw, field in (({"amount": "0"}, "amount"), ({"amount": "abc"}, "amount"), ({"months": 0}, "months"), ({"months": 25}, "months"),
                      ({"first": _month(-1)}, "first_month"), ({"account": "Piggy bank"}, "payment_account")):
        r = _give(admin_client, wid, **kw)
        assert r.status_code == 422 and field in r.get_json()["fields"], kw
    with app.app_context():
        assert SalaryAdvance.query.count() == 0


def test_only_the_admin_gives_or_sees_advances(app, client, accounts_client, manager_client):
    wid = _worker(app)
    for c in (client, accounts_client, manager_client):
        assert _give(c, wid).status_code in (403, 404)
        assert c.get(f"/api/payroll/advances?worker_id={wid}").status_code in (403, 404)
    with app.app_context():
        assert SalaryAdvance.query.count() == 0


def test_the_list_shows_each_advance_with_how_much_is_taken_back(app, admin_client):
    wid = _worker(app)
    _give(admin_client, wid, "8000", 4, first=_month(0))
    data = admin_client.get(f"/api/payroll/advances?worker_id={wid}").get_json()
    assert data["worker"]["name"] == "Ravi" and data["next_month"] == _month(1) and data["current_month"] == _month(0)
    assert len(data["advances"]) == 1 and data["advances"][0]["deducted"] == 2000.0 and "CASH" in data["accounts"]


def test_instalments_always_add_up_to_the_advance(app):
    with app.app_context():
        for amount, months in (("100.00", 3), ("1.00", 7), ("12345.67", 12), ("20000", 4)):
            adv = SalaryAdvance(amount=Decimal(amount), months=months, first_month=today_local().replace(day=1))
            assert sum(a for _, a in instalments(adv)) == Decimal(amount)

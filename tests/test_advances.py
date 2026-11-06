"""Advance salary (kohal, 2026-11-06) - money given ahead of pay, taken back in equal parts across the months that follow."""

from decimal import Decimal

from app.advances import add_months, instalments
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


def test_a_daily_wage_employees_month_share_is_split_across_the_two_pay_periods(app, admin_client):
    wid = _worker(app, "Sita", "daily_wages", "500")
    _give(admin_client, wid, "10000", 4, first=_month(0))                      # 2,500 this month
    rows = sorted(_row(admin_client, wid), key=lambda r: r["period_start"])
    assert [r["advance_deduction"] for r in rows] == [1250.0, 1250.0]
    odd = _worker(app, "Gita", "contractor", "500")
    _give(admin_client, odd, "5", 1, first=_month(0))
    parts = [r["advance_deduction"] for r in sorted(_row(admin_client, odd), key=lambda r: r["period_start"])]
    assert parts == [2.5, 2.5] and round(sum(parts), 2) == 5.0


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

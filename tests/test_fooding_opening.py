"""Fooding starting balance and date (kohal, 2026-11-13: "in employment management form, i want to have fooding starting date and starting
balance which is similar to account starting date and balance") - set from the employee's edit form, see app/fooding.py set_opening."""

from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import FoodingAccount, FoodingDeduction, FoodingEntry, Worker
from app.timeutil import today_local
from test_fooding import allot, daily_wage_worker


def _days_ago(n):
    return (today_local() - timedelta(days=n)).isoformat()


def _save(client, wid, day=None, balance=None, **extra):
    body = {"fooding_start_date": day, "fooding_start_balance": balance, **extra}
    return client.patch(f"/api/workforce/{wid}", json=body)


def _row(client, wid):
    return next(w for w in client.get("/api/fooding").get_json()["workers"] if w["worker_id"] == wid)


def test_a_starting_balance_and_day_start_the_fooding_from_that_day(app, admin_client):
    wid = daily_wage_worker()
    res = _save(admin_client, wid, _days_ago(4), "1500")
    assert res.status_code == 200, res.get_json()
    w = res.get_json()["worker"]
    assert (w["fooding_start_date"], w["fooding_start_balance"]) == (_days_ago(4), 1500.0)
    row = _row(admin_client, wid)
    assert row["allotted_total"] == 1500.0 and row["deducted_total"] == 1000.0           # five days (the 4 back to today) of 200
    assert row["remaining"] == 500.0 and (row["opening_amount"], row["opening_date"]) == (1500.0, _days_ago(4))


def test_a_starting_day_of_today_charges_the_day_and_the_days_after_keep_coming_off(app, admin_client):
    wid = daily_wage_worker()
    _save(admin_client, wid, _days_ago(0), "1000")
    assert _row(admin_client, wid)["remaining"] == 800.0
    with app.app_context():
        account = db.session.get(Worker, wid).fooding_account
        account.anchor_date = today_local() - timedelta(days=2)                           # two more days go by
        db.session.commit()
    assert _row(admin_client, wid)["remaining"] == 400.0


def test_zero_is_a_fine_starting_balance_and_food_is_still_charged_from_the_day(app, admin_client):
    wid = daily_wage_worker()
    _save(admin_client, wid, _days_ago(1), "0")
    assert _row(admin_client, wid)["remaining"] == -400.0


def test_the_register_starts_at_the_starting_balance_and_the_daily_food_lists_each_day(app, admin_client):
    wid = daily_wage_worker()
    _save(admin_client, wid, _days_ago(2), "900")
    reg = admin_client.get(f"/api/fooding/{wid}").get_json()
    assert reg["fooding"]["opening_amount"] == 900.0 and reg["auto_deducted"] == 600.0
    assert sorted(d["date"] for d in reg["daily_food"]) == sorted(_days_ago(n) for n in (0, 1, 2))
    assert not any(d["estimated"] for d in reg["daily_food"])


def test_nothing_is_saved_when_the_day_or_the_balance_is_wrong(app, admin_client):
    wid = daily_wage_worker()
    off = daily_wage_worker("Off", fooding_opt_in=False)
    tomorrow = (today_local() + timedelta(days=1)).isoformat()
    for kw, field in (({"day": tomorrow, "balance": "100"}, "fooding_start_date"), ({"day": "soon", "balance": "100"}, "fooding_start_date"),
                      ({"day": None, "balance": "100"}, "fooding_start_date"), ({"day": _days_ago(1), "balance": None}, "fooding_start_balance"),
                      ({"day": _days_ago(1), "balance": "-5"}, "fooding_start_balance"), ({"day": _days_ago(1), "balance": "abc"}, "fooding_start_balance")):
        r = _save(admin_client, wid, **kw)
        assert r.status_code == 422 and field in r.get_json()["fields"], kw
    r = _save(admin_client, off, _days_ago(1), "100")
    assert r.status_code == 422 and "fooding_start_date" in r.get_json()["fields"]
    with app.app_context():
        assert FoodingAccount.query.count() == 0


def test_leaving_both_blank_changes_nothing_and_an_unchanged_save_does_not_recalculate(app, admin_client, accounts_client):
    wid = daily_wage_worker()
    assert _save(admin_client, wid).status_code == 200                                       # both blank: nothing set
    with app.app_context():
        assert FoodingAccount.query.count() == 0
    _save(admin_client, wid, _days_ago(1), "1000")
    allot(accounts_client, wid, {"amount": "300", "payment_mode": "CASH"})
    before = _row(admin_client, wid)
    assert before["allotted_total"] == 1300.0
    assert _save(admin_client, wid, _days_ago(1), "1000", phone="9999999999").status_code == 200      # the same values, another field edited
    assert _row(admin_client, wid) == before
    assert _save(admin_client, wid).status_code == 200                                        # blank again: the starting balance stays
    assert _row(admin_client, wid)["opening_amount"] == 1000.0


def test_an_account_with_history_counts_only_from_the_starting_day_and_nothing_is_deleted(app, admin_client, accounts_client):
    wid = daily_wage_worker()
    allot(accounts_client, wid, {"amount": "2000", "payment_mode": "CASH"})
    with app.app_context():
        account = db.session.get(Worker, wid).fooding_account
        entry = FoodingEntry.query.filter_by(account_id=account.id, kind="allot").one()
        entry.entry_date = today_local() - timedelta(days=10)                                 # credited long before the starting day
        account.anchor_date = today_local() - timedelta(days=3)
        account.deductions.append(FoodingDeduction(day=today_local() - timedelta(days=6), amount=Decimal("200")))
        account.deducted_total = Decimal("1400")
        db.session.commit()
    allot(accounts_client, wid, {"amount": "500", "payment_mode": "CASH"})                    # credited today, so after the starting day
    assert _save(admin_client, wid, _days_ago(2), "700").status_code == 200
    row = _row(admin_client, wid)
    assert row["allotted_total"] == 1200.0                                                    # 700 + the 500 credited after the day
    assert row["deducted_total"] == 600.0                                                     # three days of food, none of what came before
    reg = admin_client.get(f"/api/fooding/{wid}").get_json()
    assert [e["amount"] for e in reg["entries"]] == [500.0]                                   # the 2,000 credit is left out of the register
    assert all(d["date"] >= _days_ago(2) for d in reg["daily_food"]) and reg["auto_deducted"] == 600.0
    with app.app_context():                                                                   # ...but is still on record
        assert FoodingEntry.query.filter_by(kind="allot", status="approved").count() == 2
        assert FoodingDeduction.query.count() >= 4


def test_changing_the_starting_balance_or_day_gives_the_same_answer_as_setting_it_fresh(app, admin_client):
    wid = daily_wage_worker()
    _save(admin_client, wid, _days_ago(3), "1000")
    _save(admin_client, wid, _days_ago(1), "600")
    row = _row(admin_client, wid)
    assert (row["allotted_total"], row["deducted_total"]) == (600.0, 400.0)
    _save(admin_client, wid, _days_ago(3), "1000")
    row = _row(admin_client, wid)
    assert (row["allotted_total"], row["deducted_total"]) == (1000.0, 800.0)                  # four days of food again


def test_a_paused_account_is_not_charged_for_the_days_before_it_was_set(app, admin_client):
    wid = daily_wage_worker()
    admin_client.post(f"/api/fooding/{wid}/pause")
    _save(admin_client, wid, _days_ago(5), "800")
    row = _row(admin_client, wid)
    assert row["remaining"] == 800.0 and row["is_paused"]


def test_an_account_with_a_starting_balance_raises_the_topup_request_when_it_runs_low(app, admin_client):
    wid = daily_wage_worker()
    _save(admin_client, wid, _days_ago(3), "900")                                             # 900 - 4 x 200 = 100, under one day's food
    _row(admin_client, wid)
    with app.app_context():
        requests = FoodingEntry.query.filter_by(kind="allot", status="pending").all()
        assert len(requests) == 1 and requests[0].is_auto

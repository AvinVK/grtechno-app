"""Fooding: a daily-wage employee's food allowance (kohal, 2026-10-18) - see app/fooding.py and
models.FoodingAccount for the no-cron settle() design this all rests on."""

from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import FoodingAccount, Worker
from conftest import make_user, signed_in


def daily_wage_worker(name="Deepak Daily", wage_amount=None):
    worker = Worker(name=name, category="manpower", employment_type="daily_wages", wage_amount=wage_amount)
    db.session.add(worker)
    db.session.commit()
    return worker.id


def daily_wage_user(app, name="Deepak Daily", pin="285193"):
    """A signed-in User with a matching daily-wage Worker, linked the way sync_worker_for_user would -
    skips the real /set-pin HTTP flow since only the link matters here, not that flow itself (already
    covered in test_workforce.py)."""
    user = make_user(name, pin=pin)
    worker = Worker(name=name, category="manpower", employment_type="daily_wages", user_code=user.code)
    db.session.add(worker)
    db.session.commit()
    return signed_in(app, user), worker.id


# ---------- admin/accountant management ----------

def test_only_admin_or_accountant_can_manage_fooding(client, accounts_client, admin_client):
    with_wid = daily_wage_worker()
    assert client.get("/api/fooding").status_code == 403
    assert accounts_client.get("/api/fooding").status_code == 200
    assert admin_client.get("/api/fooding").status_code == 200
    assert client.post(f"/api/fooding/{with_wid}/allot", json={"amount": 100}).status_code == 403


def test_fooding_lists_every_daily_wage_worker_starting_at_zero(admin_client):
    wid = daily_wage_worker()
    with_salary = Worker(name="Sanjay Salary", category="staff", employment_type="regular")
    db.session.add(with_salary)
    db.session.commit()

    data = admin_client.get("/api/fooding").get_json()
    ids = [w["worker_id"] for w in data["workers"]]
    assert wid in ids and with_salary.id not in ids
    row = next(w for w in data["workers"] if w["worker_id"] == wid)
    assert row["allotted_total"] == 0.0 and row["remaining"] == 0.0 and row["is_paused"] is False
    assert data["daily_amount"] == 200.0


def test_allotting_money_creates_the_account(accounts_client):
    wid = daily_wage_worker()
    res = accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "1000"})
    assert res.status_code == 200
    body = res.get_json()["fooding"]
    assert body["allotted_total"] == 1000.0 and body["remaining"] == 1000.0


def test_a_second_allotment_adds_to_the_balance_not_replaces_it(accounts_client):
    """kohal, 2026-10-18 (answered): "Adds to the remaining balance"."""
    wid = daily_wage_worker()
    accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "1000"})
    res = accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "500"})
    body = res.get_json()["fooding"]
    assert body["allotted_total"] == 1500.0 and body["remaining"] == 1500.0


def test_allot_amount_must_be_a_positive_number(accounts_client):
    wid = daily_wage_worker()
    for bad in ("0", "-5", "abc", ""):
        res = accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": bad})
        assert res.status_code == 422 and "amount" in res.get_json()["fields"], bad


def test_allot_pause_and_resume_only_work_on_a_daily_wage_worker(accounts_client):
    salary_worker = Worker(name="Sanjay Salary", category="staff", employment_type="regular")
    db.session.add(salary_worker)
    db.session.commit()
    assert accounts_client.post(f"/api/fooding/{salary_worker.id}/allot", json={"amount": "100"}).status_code == 404
    assert accounts_client.post(f"/api/fooding/{salary_worker.id}/pause").status_code == 404


def test_the_daily_amount_is_deducted_without_a_cron(app, accounts_client):
    """No scheduled job applies the 200/day (see FoodingAccount.settle's own docstring) - it's caught up
    live, the moment the account is next read or changed."""
    wid = daily_wage_worker()
    accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "1000"})
    with app.app_context():
        account = db.session.get(Worker, wid).fooding_account
        account.anchor_date = date.today() - timedelta(days=3)
        db.session.commit()

    data = accounts_client.get("/api/fooding").get_json()
    row = next(w for w in data["workers"] if w["worker_id"] == wid)
    assert row["deducted_total"] == 600.0 and row["remaining"] == 400.0   # 3 days * 200


def test_pausing_stops_the_daily_deduction(app, accounts_client):
    wid = daily_wage_worker()
    accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "1000"})
    accounts_client.post(f"/api/fooding/{wid}/pause")
    with app.app_context():
        account = db.session.get(Worker, wid).fooding_account
        account.anchor_date = date.today() - timedelta(days=5)
        db.session.commit()

    data = accounts_client.get("/api/fooding").get_json()
    row = next(w for w in data["workers"] if w["worker_id"] == wid)
    assert row["is_paused"] is True and row["remaining"] == 1000.0 and row["deducted_total"] == 0.0


def test_resuming_picks_up_the_daily_deduction_again(app, accounts_client):
    wid = daily_wage_worker()
    accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "1000"})
    accounts_client.post(f"/api/fooding/{wid}/pause")
    res = accounts_client.post(f"/api/fooding/{wid}/resume")
    assert res.status_code == 200 and res.get_json()["fooding"]["is_paused"] is False
    with app.app_context():
        account = db.session.get(Worker, wid).fooding_account
        account.anchor_date = date.today() - timedelta(days=2)
        db.session.commit()
    data = accounts_client.get("/api/fooding").get_json()
    row = next(w for w in data["workers"] if w["worker_id"] == wid)
    assert row["remaining"] == 600.0   # 2 days * 200 off 1000


def test_remaining_never_goes_below_zero(app, accounts_client):
    wid = daily_wage_worker()
    accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "250"})
    with app.app_context():
        account = db.session.get(Worker, wid).fooding_account
        account.anchor_date = date.today() - timedelta(days=10)   # 10 * 200 = 2000, way more than the 250 allotted
        db.session.commit()

    data = accounts_client.get("/api/fooding").get_json()
    row = next(w for w in data["workers"] if w["worker_id"] == wid)
    assert row["remaining"] == 0.0 and row["deducted_total"] == 250.0   # capped, not negative or over-deducted


def test_topping_up_after_running_dry_does_not_retroactively_owe_the_zero_days(app, accounts_client):
    """settle() always re-anchors to today, so the gap while the balance sat at zero is never counted
    again once it's topped up - see FoodingAccount.settle's own docstring."""
    wid = daily_wage_worker()
    accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "200"})
    with app.app_context():
        account = db.session.get(Worker, wid).fooding_account
        account.anchor_date = date.today() - timedelta(days=10)
        db.session.commit()
    accounts_client.get("/api/fooding")   # settles it to 0 remaining, re-anchors to today

    res = accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "100"})
    assert res.get_json()["fooding"]["remaining"] == 100.0   # not silently clobbered by the stale gap


# ---------- the daily-wage worker's own view ----------

def test_fooding_page_and_api_need_a_daily_wage_worker(client, admin_client):
    assert client.get("/fooding").status_code == 403       # plain user, not daily-wage
    assert client.get("/api/fooding/me").status_code == 403
    assert admin_client.get("/fooding").status_code == 403  # the admin has no Worker row at all


def test_a_daily_wage_worker_sees_their_own_balance(app, accounts_client):
    who, wid = daily_wage_user(app)
    accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "750"})

    assert who.get("/fooding").status_code == 200
    data = who.get("/api/fooding/me").get_json()["fooding"]
    assert data["allotted_total"] == 750.0 and data["remaining"] == 750.0 and data["is_paused"] is False


def test_the_me_hub_renders_the_wages_and_fooding_tiles(app):
    """A plain GET renders the actual Jinja template, not just the JSON API - the one place a template-only
    bug (an undefined macro, say) would otherwise go unnoticed by every other test here."""
    who, _ = daily_wage_user(app)
    html = who.get("/me").get_data(as_text=True)
    assert html.count("Wages</span>") == 1 and html.count("Fooding</span>") == 1
    assert 'href="/wages"' in html and 'href="/fooding"' in html


def test_a_paused_daily_wage_worker_sees_paused(app, accounts_client):
    """kohal, 2026-10-18: "if paused by admin or accountant, the daily wages user should see paused in
    fooding tab"."""
    who, wid = daily_wage_user(app)
    accounts_client.post(f"/api/fooding/{wid}/allot", json={"amount": "500"})
    accounts_client.post(f"/api/fooding/{wid}/pause")

    data = who.get("/api/fooding/me").get_json()["fooding"]
    assert data["is_paused"] is True


def test_a_daily_wage_worker_with_nothing_allotted_yet_sees_zeroes_not_an_error(app):
    who, wid = daily_wage_user(app)
    data = who.get("/api/fooding/me").get_json()["fooding"]
    assert data["allotted_total"] == 0.0 and data["remaining"] == 0.0 and data["is_paused"] is False


# ---------- Wages (placeholder) ----------

def test_wages_page_and_api_need_a_daily_wage_worker(client):
    assert client.get("/wages").status_code == 403
    assert client.get("/api/wages/me").status_code == 403


def test_wages_shows_the_configured_daily_rate(app):
    user = make_user("Rakesh Rate", pin="285193")
    worker = Worker(name="Rakesh Rate", category="manpower", employment_type="daily_wages",
                     user_code=user.code, wage_amount=Decimal("450"))
    db.session.add(worker)
    db.session.commit()
    who = signed_in(app, user)
    assert who.get("/wages").status_code == 200
    data = who.get("/api/wages/me").get_json()
    assert data["daily_rate"] == 450.0


def test_wages_with_no_rate_set_shows_none_not_an_error(app):
    who, _ = daily_wage_user(app)
    data = who.get("/api/wages/me").get_json()
    assert data["daily_rate"] is None

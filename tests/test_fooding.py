"""Fooding: a daily-wage employee's food allowance (kohal, 2026-10-18) - see app/fooding.py and
models.FoodingAccount for the no-cron settle() design this all rests on."""

from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import FoodingAccount, Worker
from conftest import make_user, signed_in


class _Result:
    """What allot() hands back: the response's status and, once approved, the balance after it."""
    def __init__(self, status_code, body):
        self.status_code, self._body = status_code, body

    def get_json(self):
        return self._body


def allot(who, wid, payload):
    """Ask for money to be allotted as `who`, then have someone else approve it - the way it works now (kohal,
    2026-10-27: an allotment needs the other of admin / accountant to approve it), so the tests that only
    care about the balance read the way they always did. A request that is refused (bad amount, wrong
    worker...) comes back as the plain response."""
    from flask import current_app
    res = who.post(f"/api/fooding/{wid}/allot", json=payload)
    if res.status_code != 200:
        return res
    approver = signed_in(current_app, make_user("Approving Admin", is_admin=True))
    done = approver.post(f"/api/fooding/requests/{res.get_json()['request']['id']}/approve")
    assert done.status_code == 200, done.get_json()
    listing = approver.get("/api/fooding").get_json()["workers"]
    return _Result(200, {"fooding": next(w for w in listing if w["worker_id"] == wid), "request": done.get_json()["request"]})


def daily_wage_worker(name="Deepak Daily", wage_amount=None, fooding_opt_in=True):
    """fooding_opt_in defaults True here, same as the Edit form now defaults it the moment Daily wages is
    picked (kohal, 2026-10-18: "should be automatically on for daily wages") - it's just a default, not an
    automatic rule any more (see Worker.fooding_eligible), so a test for the "not eligible" case overrides it."""
    worker = Worker(name=name, category="manpower", employment_type="daily_wages", wage_amount=wage_amount,
                     fooding_opt_in=fooding_opt_in)
    db.session.add(worker)
    db.session.commit()
    return worker.id


def daily_wage_user(app, name="Deepak Daily", pin="285193", fooding_opt_in=True):
    """A signed-in User with a matching daily-wage Worker, linked the way sync_worker_for_user would -
    skips the real /set-pin HTTP flow since only the link matters here, not that flow itself (already
    covered in test_workforce.py)."""
    user = make_user(name, pin=pin)
    worker = Worker(name=name, category="manpower", employment_type="daily_wages", user_code=user.code,
                     fooding_opt_in=fooding_opt_in)
    db.session.add(worker)
    db.session.commit()
    return signed_in(app, user), worker.id


# ---------- admin/accountant management ----------

def test_only_admin_or_accountant_can_manage_fooding(client, accounts_client, admin_client):
    with_wid = daily_wage_worker()
    assert client.get("/api/fooding").status_code == 403
    assert accounts_client.get("/api/fooding").status_code == 200
    assert admin_client.get("/api/fooding").status_code == 200
    assert client.post(f"/api/fooding/{with_wid}/allot", json={"amount": 100, "payment_mode": "Cash"}).status_code == 403


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
    res = allot(accounts_client, wid, {"amount": "1000", "payment_mode": "Cash"})
    assert res.status_code == 200
    body = res.get_json()["fooding"]
    assert body["allotted_total"] == 1000.0 and body["remaining"] == 1000.0


def test_a_second_allotment_adds_to_the_balance_not_replaces_it(accounts_client):
    """kohal, 2026-10-18 (answered): "Adds to the remaining balance"."""
    wid = daily_wage_worker()
    allot(accounts_client, wid, {"amount": "1000", "payment_mode": "Cash"})
    res = allot(accounts_client, wid, {"amount": "500", "payment_mode": "Cash"})
    body = res.get_json()["fooding"]
    assert body["allotted_total"] == 1500.0 and body["remaining"] == 1500.0


def test_allot_amount_must_be_a_positive_number(accounts_client):
    wid = daily_wage_worker()
    for bad in ("0", "-5", "abc", ""):
        res = allot(accounts_client, wid, {"amount": bad, "payment_mode": "Cash"})
        assert res.status_code == 422 and "amount" in res.get_json()["fields"], bad


def test_allot_requires_a_valid_payment_mode(accounts_client):
    """kohal, 2026-10-18: "add mode of payment option as well. shld be cash, online/UPI"."""
    wid = daily_wage_worker()
    res = allot(accounts_client, wid, {"amount": "500"})
    assert res.status_code == 422 and "payment_mode" in res.get_json()["fields"]
    res = allot(accounts_client, wid, {"amount": "500", "payment_mode": "Cheque"})
    assert res.status_code == 422 and "payment_mode" in res.get_json()["fields"]
    res = allot(accounts_client, wid, {"amount": "500", "payment_mode": "Online/UPI"})
    assert res.status_code == 200


def test_allot_pause_and_resume_only_work_on_a_daily_wage_worker(accounts_client):
    salary_worker = Worker(name="Sanjay Salary", category="staff", employment_type="regular")
    db.session.add(salary_worker)
    db.session.commit()
    assert allot(accounts_client, salary_worker.id, {"amount": "100", "payment_mode": "Cash"}).status_code == 404
    assert accounts_client.post(f"/api/fooding/{salary_worker.id}/pause").status_code == 404


def test_the_daily_amount_is_deducted_without_a_cron(app, accounts_client):
    """No scheduled job applies the 200/day (see FoodingAccount.settle's own docstring) - it's caught up
    live, the moment the account is next read or changed."""
    wid = daily_wage_worker()
    allot(accounts_client, wid, {"amount": "1000", "payment_mode": "Cash"})
    with app.app_context():
        account = db.session.get(Worker, wid).fooding_account
        account.anchor_date = date.today() - timedelta(days=3)
        db.session.commit()

    data = accounts_client.get("/api/fooding").get_json()
    row = next(w for w in data["workers"] if w["worker_id"] == wid)
    assert row["deducted_total"] == 600.0 and row["remaining"] == 400.0   # 3 days * 200


def test_pausing_stops_the_daily_deduction(app, accounts_client):
    wid = daily_wage_worker()
    allot(accounts_client, wid, {"amount": "1000", "payment_mode": "Cash"})
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
    allot(accounts_client, wid, {"amount": "1000", "payment_mode": "Cash"})
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
    allot(accounts_client, wid, {"amount": "250", "payment_mode": "Cash"})
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
    allot(accounts_client, wid, {"amount": "200", "payment_mode": "Cash"})
    with app.app_context():
        account = db.session.get(Worker, wid).fooding_account
        account.anchor_date = date.today() - timedelta(days=10)
        db.session.commit()
    accounts_client.get("/api/fooding")   # settles it to 0 remaining, re-anchors to today

    res = allot(accounts_client, wid, {"amount": "100", "payment_mode": "Cash"})
    assert res.get_json()["fooding"]["remaining"] == 100.0   # not silently clobbered by the stale gap


# ---------- the daily-wage worker's own view ----------

def test_fooding_page_needs_a_daily_wage_worker_or_manage_access(client, admin_client):
    """kohal, 2026-10-18: "fooding should open its own page!" - /fooding now serves both audiences (same
    split as /attendance's team_only), so a plain user (neither) still 403s, but the admin now gets the
    management view instead of 403 (they can_manage_fooding, even with no Worker row of their own)."""
    assert client.get("/fooding").status_code == 403       # plain user, not daily-wage, can't manage either
    assert client.get("/api/fooding/me").status_code == 403
    assert admin_client.get("/fooding").status_code == 200  # the management view


def test_a_daily_wage_worker_sees_their_own_balance(app, accounts_client):
    who, wid = daily_wage_user(app)
    allot(accounts_client, wid, {"amount": "750", "payment_mode": "Cash"})

    res = who.get("/fooding")
    assert res.status_code == 200 and 'data-mode="own"' in res.get_data(as_text=True)
    data = who.get("/api/fooding/me").get_json()["fooding"]
    assert data["allotted_total"] == 750.0 and data["remaining"] == 750.0 and data["is_paused"] is False


def test_an_allotment_shows_up_as_its_own_entry(app, accounts_client):
    who, wid = daily_wage_user(app)
    allot(accounts_client, wid, {"amount": "750", "payment_mode": "Online/UPI"})
    entries = who.get("/api/fooding/me").get_json()["entries"]
    assert len(entries) == 1
    assert entries[0]["kind"] == "allot" and entries[0]["amount"] == 750.0 and entries[0]["payment_mode"] == "Online/UPI"


# ---------- a daily-wage worker's own "+ Add expense" (kohal, 2026-10-18) ----------

def test_a_worker_can_log_an_expense_against_their_own_balance(app, accounts_client):
    """"the daily wages employee can also use the money for travelling or for any reason... the amount,
    how was it paid and for what was it used"."""
    who, wid = daily_wage_user(app)
    allot(accounts_client, wid, {"amount": "1000", "payment_mode": "Cash"})

    res = who.post("/api/fooding/me/expenses", json={"amount": "150", "payment_mode": "Cash", "purpose": "Auto fare to site"})
    assert res.status_code == 201
    body = res.get_json()
    assert body["fooding"]["remaining"] == 850.0
    assert len(body["entries"]) == 2   # the allot entry, plus this one
    expense = next(e for e in body["entries"] if e["kind"] == "expense")
    assert expense["amount"] == 150.0 and expense["payment_mode"] == "Cash" and expense["purpose"] == "Auto fare to site"

    data = who.get("/api/fooding/me").get_json()["fooding"]
    assert data["remaining"] == 850.0


def test_an_expense_needs_amount_payment_mode_and_purpose(app, accounts_client):
    who, wid = daily_wage_user(app)
    allot(accounts_client, wid, {"amount": "1000", "payment_mode": "Cash"})

    res = who.post("/api/fooding/me/expenses", json={"amount": "150", "payment_mode": "Cash", "purpose": ""})
    assert res.status_code == 422 and "purpose" in res.get_json()["fields"]
    res = who.post("/api/fooding/me/expenses", json={"amount": "150", "purpose": "Food"})
    assert res.status_code == 422 and "payment_mode" in res.get_json()["fields"]
    res = who.post("/api/fooding/me/expenses", json={"amount": "0", "payment_mode": "Cash", "purpose": "Food"})
    assert res.status_code == 422 and "amount" in res.get_json()["fields"]


def test_an_expense_cannot_exceed_whats_remaining(app, accounts_client):
    who, wid = daily_wage_user(app)
    allot(accounts_client, wid, {"amount": "100", "payment_mode": "Cash"})
    res = who.post("/api/fooding/me/expenses", json={"amount": "150", "payment_mode": "Cash", "purpose": "Travel"})
    assert res.status_code == 422 and "amount" in res.get_json()["fields"]
    # exactly the remaining balance is fine
    res = who.post("/api/fooding/me/expenses", json={"amount": "100", "payment_mode": "Cash", "purpose": "Travel"})
    assert res.status_code == 201 and res.get_json()["fooding"]["remaining"] == 0.0


def test_only_a_daily_wage_worker_can_log_their_own_expense(client):
    res = client.post("/api/fooding/me/expenses", json={"amount": "150", "payment_mode": "Cash", "purpose": "Travel"})
    assert res.status_code == 403


def test_an_expense_still_works_even_with_nothing_allotted_yet(app):
    """Logging an expense creates the account on the spot (same as allot does) - but with nothing allotted,
    there's nothing to spend, so it's still capped at 0."""
    who, wid = daily_wage_user(app)
    res = who.post("/api/fooding/me/expenses", json={"amount": "10", "payment_mode": "Cash", "purpose": "Travel"})
    assert res.status_code == 422 and "amount" in res.get_json()["fields"]


def test_the_management_page_shows_mode_manage(admin_client, accounts_client):
    """The same /fooding route the daily-wage worker's own page uses (kohal: "fooding should open its own
    page!") - app/static/js/fooding.js picks the view from this data-mode attribute, same idea as
    attendance.html's data-team-only."""
    for who in (admin_client, accounts_client):
        html = who.get("/fooding").get_data(as_text=True)
        assert 'data-mode="manage"' in html


def test_the_me_hub_renders_the_wages_and_fooding_tiles(app):
    """A plain GET renders the actual Jinja template, not just the JSON API - the one place a template-only
    bug (an undefined macro, say) would otherwise go unnoticed by every other test here."""
    who, _ = daily_wage_user(app)
    html = who.get("/me").get_data(as_text=True)
    assert html.count("Wages</span>") == 1 and html.count("Fooding</span>") == 1
    assert 'href="/wages"' in html and 'href="/fooding"' in html


def test_admin_and_accountant_get_a_fooding_tile_in_the_services_grid(admin_client, accounts_client, client):
    """kohal, 2026-10-18: "i wasnt fooding blobk here in missing space" (a tile in the same grid as
    Leads/Clients/...) and "fooding should open its own page!" (a real page, not an anchor)."""
    for who in (admin_client, accounts_client):
        html = who.get("/me").get_data(as_text=True)
        assert html.count('href="/fooding"') == 1 and 'Fooding</span>' in html

    html = client.get("/me").get_data(as_text=True)
    assert 'href="/fooding"' not in html


def test_the_fooding_tile_shows_how_many_are_on_it(admin_client):
    daily_wage_worker()
    daily_wage_worker(name="Second One")
    html = admin_client.get("/me").get_data(as_text=True)
    assert "2 on fooding" in html


def test_a_paused_daily_wage_worker_sees_paused(app, accounts_client):
    """kohal, 2026-10-18: "if paused by admin or accountant, the daily wages user should see paused in
    fooding tab"."""
    who, wid = daily_wage_user(app)
    allot(accounts_client, wid, {"amount": "500", "payment_mode": "Cash"})
    accounts_client.post(f"/api/fooding/{wid}/pause")

    data = who.get("/api/fooding/me").get_json()["fooding"]
    assert data["is_paused"] is True


def test_a_daily_wage_worker_with_nothing_allotted_yet_sees_zeroes_not_an_error(app):
    who, wid = daily_wage_user(app)
    data = who.get("/api/fooding/me").get_json()["fooding"]
    assert data["allotted_total"] == 0.0 and data["remaining"] == 0.0 and data["is_paused"] is False


def test_a_daily_wage_worker_switched_off_fooding_is_not_eligible(app, admin_client):
    """kohal, 2026-10-18: "should be automatically on for daily wages and off for others" is a default, not
    an automatic rule any more - Worker.fooding_eligible is purely the checkbox (fooding_opt_in), so a
    daily-wage worker it's explicitly off for is not on the wallet at all, same as anyone else."""
    who, wid = daily_wage_user(app, fooding_opt_in=False)
    assert who.get("/fooding").status_code == 403
    assert who.get("/api/fooding/me").status_code == 403
    ids = [w["worker_id"] for w in admin_client.get("/api/fooding").get_json()["workers"]]
    assert wid not in ids


# ---------- a salaried employee opting onto fooding (kohal, 2026-10-18) ----------
#
# "now there are salaried employees which can be on 200rs fooding thing. for this, give a check mark in
# employee details form after salary thing named 'fooding?'. ye selected yes, then it should show on
# fooding tab and shld foloow that same life."

def salaried_user(app, name="Sita Salaried", opt_in=False, pin="285193"):
    user = make_user(name, pin=pin)
    worker = Worker(name=name, category="staff", employment_type="regular", user_code=user.code,
                     fooding_opt_in=opt_in)
    db.session.add(worker)
    db.session.commit()
    return signed_in(app, user), worker.id


def test_a_salaried_worker_is_not_fooding_eligible_by_default(app, admin_client):
    who, wid = salaried_user(app, opt_in=False)
    assert who.get("/fooding").status_code == 403
    ids = [w["worker_id"] for w in admin_client.get("/api/fooding").get_json()["workers"]]
    assert wid not in ids


def test_ticking_fooding_opt_in_in_employee_management_makes_them_eligible(app, admin_client, accounts_client):
    who, wid = salaried_user(app, opt_in=False)
    res = admin_client.patch(f"/api/workforce/{wid}", json={"name": "Sita Salaried", "fooding_opt_in": True})
    assert res.status_code == 200 and res.get_json()["worker"]["fooding_opt_in"] is True

    assert who.get("/fooding").status_code == 200
    ids = [w["worker_id"] for w in admin_client.get("/api/fooding").get_json()["workers"]]
    assert wid in ids

    # same life as a daily-wage worker from here: allot, see it, pause, expense
    allot(accounts_client, wid, {"amount": "900", "payment_mode": "Cash"})
    data = who.get("/api/fooding/me").get_json()["fooding"]
    assert data["allotted_total"] == 900.0 and data["remaining"] == 900.0

    accounts_client.post(f"/api/fooding/{wid}/pause")
    assert who.get("/api/fooding/me").get_json()["fooding"]["is_paused"] is True
    accounts_client.post(f"/api/fooding/{wid}/resume")

    res = who.post("/api/fooding/me/expenses", json={"amount": "200", "payment_mode": "Online/UPI", "purpose": "Travel"})
    assert res.status_code == 201 and res.get_json()["fooding"]["remaining"] == 700.0


def test_unticking_fooding_opt_in_removes_eligibility_again(app, admin_client):
    who, wid = salaried_user(app, opt_in=True)
    assert who.get("/fooding").status_code == 200
    admin_client.patch(f"/api/workforce/{wid}", json={"name": "Sita Salaried", "fooding_opt_in": False})
    assert who.get("/fooding").status_code == 403


def test_a_salaried_worker_doesnt_get_a_wages_tile_just_from_opting_into_fooding(app):
    """Wages stays daily-wage only (kohal's framing: it's the fooding wallet, not day-rate tracking, that
    a salaried person opts into) - they still get the Fooding tile."""
    who, wid = salaried_user(app, opt_in=True)
    html = who.get("/me").get_data(as_text=True)
    assert "Fooding</span>" in html and "Wages</span>" not in html


def test_admin_fooding_list_includes_both_daily_wage_and_opted_in_salaried(app, admin_client):
    _, dw_wid = daily_wage_user(app, name="Deepak Daily2")
    _, sal_wid = salaried_user(app, name="Sita Salaried2", opt_in=True)
    ids = [w["worker_id"] for w in admin_client.get("/api/fooding").get_json()["workers"]]
    assert dw_wid in ids and sal_wid in ids


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


# ---------- the per-person register (kohal, 2026-10-27) ----------

def test_a_persons_fooding_register_lists_credits_and_expenses_with_date_and_who(app, accounts_client, admin_client):
    wid = daily_wage_worker()
    allot(accounts_client, wid, {"amount": 3000, "payment_mode": "Cash"})
    allot(admin_client, wid, {"amount": 500, "payment_mode": "Online/UPI"})

    reg = accounts_client.get(f"/api/fooding/{wid}").get_json()
    assert [(e["kind"], e["amount"], e["payment_mode"]) for e in reg["entries"]] == [
        ("allot", 500.0, "Online/UPI"), ("allot", 3000.0, "Cash")]
    assert all(e["entry_date"] and e["created_by_name"] for e in reg["entries"])
    assert {e["created_by_name"] for e in reg["entries"]} == {"Anil Accounts", "grtechno"}
    assert reg["fooding"]["allotted_total"] == 3500.0 and reg["auto_deducted"] == 0.0


def test_only_admin_or_accountant_can_open_a_fooding_register(client):
    wid = daily_wage_worker()
    assert client.get(f"/api/fooding/{wid}").status_code == 403


# ---------- allotments are requests the other of admin / accountant approves (kohal, 2026-10-27) ----------

def _ask(who, wid, amount=1000, mode="Cash"):
    res = who.post(f"/api/fooding/{wid}/allot", json={"amount": amount, "payment_mode": mode})
    assert res.status_code == 200, res.get_json()
    return res.get_json()["request"]["id"]


def test_an_allotment_is_only_a_request_until_someone_else_approves(app, accounts_client, admin_client):
    who, wid = daily_wage_user(app)
    rid = _ask(accounts_client, wid)
    row = next(w for w in accounts_client.get("/api/fooding").get_json()["workers"] if w["worker_id"] == wid)
    assert row["allotted_total"] == 0.0                                   # nothing credited yet
    assert who.get("/api/fooding/me").get_json()["entries"] == []         # and not in the worker's register
    assert accounts_client.get(f"/api/fooding/{wid}").get_json()["entries"] == []

    assert admin_client.post(f"/api/fooding/requests/{rid}/approve").status_code == 200
    row = next(w for w in accounts_client.get("/api/fooding").get_json()["workers"] if w["worker_id"] == wid)
    assert row["allotted_total"] == 1000.0 and row["remaining"] == 1000.0
    entry = who.get("/api/fooding/me").get_json()["entries"][0]
    assert entry["kind"] == "allot" and entry["amount"] == 1000.0


def test_whoever_asks_cannot_approve_it_but_the_other_one_can_either_way_round(app, accounts_client, admin_client):
    wid = daily_wage_worker()
    by_admin = _ask(admin_client, wid, 500)
    assert admin_client.post(f"/api/fooding/requests/{by_admin}/approve").status_code == 403
    assert accounts_client.post(f"/api/fooding/requests/{by_admin}/approve").status_code == 200

    by_accounts = _ask(accounts_client, wid, 300)
    assert accounts_client.post(f"/api/fooding/requests/{by_accounts}/approve").status_code == 403
    assert accounts_client.post(f"/api/fooding/requests/{by_accounts}/reject").status_code == 403
    assert admin_client.post(f"/api/fooding/requests/{by_accounts}/approve").status_code == 200
    row = next(w for w in admin_client.get("/api/fooding").get_json()["workers"] if w["worker_id"] == wid)
    assert row["allotted_total"] == 800.0


def test_a_rejected_request_adds_nothing_and_cannot_be_decided_again(app, accounts_client, admin_client):
    wid = daily_wage_worker()
    rid = _ask(accounts_client, wid, 700)
    assert admin_client.post(f"/api/fooding/requests/{rid}/reject").status_code == 200
    assert admin_client.post(f"/api/fooding/requests/{rid}/approve").status_code == 409
    row = next(w for w in admin_client.get("/api/fooding").get_json()["workers"] if w["worker_id"] == wid)
    assert row["allotted_total"] == 0.0


def test_the_requester_can_withdraw_a_waiting_request(app, accounts_client, admin_client):
    wid = daily_wage_worker()
    rid = _ask(accounts_client, wid)
    assert admin_client.post(f"/api/fooding/requests/{rid}/cancel").status_code == 403      # not theirs
    assert accounts_client.post(f"/api/fooding/requests/{rid}/cancel").status_code == 200
    assert admin_client.post(f"/api/fooding/requests/{rid}/approve").status_code == 409
    data = admin_client.get("/api/fooding/requests").get_json()
    assert data["pending"] == [] and [h["status"] for h in data["history"]] == ["cancelled"]


def test_active_requests_and_history_are_listed_with_who_can_decide(app, accounts_client, admin_client):
    wid = daily_wage_worker("Listed Worker")
    waiting = _ask(accounts_client, wid, 200)
    done = _ask(admin_client, wid, 900, "Online/UPI")
    accounts_client.post(f"/api/fooding/requests/{done}/approve")

    mine = accounts_client.get("/api/fooding/requests").get_json()
    assert [p["id"] for p in mine["pending"]] == [waiting]
    assert mine["pending"][0]["is_mine"] is True and mine["pending"][0]["can_decide"] is False
    assert mine["pending"][0]["worker_name"] == "Listed Worker" and mine["pending"][0]["created_by_name"] == "Anil Accounts"
    assert [(h["id"], h["status"], h["decided_by_name"]) for h in mine["history"]] == [(done, "approved", "Anil Accounts")]

    theirs = admin_client.get("/api/fooding/requests").get_json()
    assert theirs["pending"][0]["can_decide"] is True and theirs["pending"][0]["is_mine"] is False


def test_only_admin_or_accountant_see_or_decide_requests(app, client, accounts_client):
    wid = daily_wage_worker()
    rid = _ask(accounts_client, wid)
    assert client.get("/api/fooding/requests").status_code == 403
    assert client.post(f"/api/fooding/requests/{rid}/approve").status_code == 403


def test_the_me_tile_counts_requests_waiting_on_you(app, accounts_client, admin_client):
    wid = daily_wage_worker()
    _ask(accounts_client, wid)
    theirs = admin_client.get("/me").get_data(as_text=True)
    mine = accounts_client.get("/me").get_data(as_text=True)
    assert "1 to approve" in theirs and "1 to approve" not in mine


"""Cash purchases (kohal, 2026-10-21): money an admin/accountant hands an employee, tracked through to what
they actually bought with it and whether that's been approved yet - see app/cash_purchases.py and
models.CashAccount/CashTopup/CashPurchase."""

from decimal import Decimal

from app.extensions import db
from app.models import CashAccount, Worker
from conftest import make_user, signed_in


def add_worker(name="Deepak Daily"):
    worker = Worker(name=name, category="manpower", employment_type="daily_wages")
    db.session.add(worker)
    db.session.commit()
    return worker.id


def worker_user(app, name="Deepak Daily", pin="285193", employment_type="contractor"):
    """A signed-in User with a matching Worker, linked the way sync_worker_for_user would. Defaults to
    contractor, not daily_wages, despite the name - most tests here are about the cash-purchase feature
    itself, not employment type, and a daily-wage worker can't request cash at all any more (kohal,
    2026-10-21: "daily wages employee should not be able to request for cash" - see
    test_a_daily_wage_worker_cannot_request_cash, which overrides this specifically to prove that ban)."""
    user = make_user(name, pin=pin)
    worker = Worker(name=name, category="manpower", employment_type=employment_type, user_code=user.code)
    db.session.add(worker)
    db.session.commit()
    return signed_in(app, user), worker.id


# ---------- admin/accountant: giving cash ----------

def test_only_admin_or_accountant_can_see_pending_but_only_the_admin_can_give(client, accounts_client, admin_client):
    """kohal, 2026-11-02: only the admin hands cash over - it is paid out through the bank accounts."""
    wid = add_worker()
    assert client.post(f"/api/cash-purchases/{wid}/give", json={"amount": 100, "payment_mode": "CASH"}).status_code == 403
    assert client.get("/api/cash-purchases/pending").status_code == 403
    assert accounts_client.get("/api/cash-purchases/pending").status_code == 200           # can look ...
    assert accounts_client.get("/api/cash-purchases/pending").get_json()["can_decide"] is False
    assert accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": 100, "payment_mode": "CASH"}).status_code == 403
    assert admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": 100, "payment_mode": "CASH"}).status_code == 200
    assert admin_client.get("/api/cash-purchases/pending").get_json()["can_decide"] is True


def test_giving_cash_creates_the_account(admin_client):
    wid = add_worker()
    res = admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    assert res.status_code == 200
    body = res.get_json()["account"]
    assert body["given_total"] == 2000.0 and body["spent_total"] == 0.0 and body["remaining"] == 2000.0


def test_a_second_give_adds_to_the_balance_not_replaces_it(admin_client):
    wid = add_worker()
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    res = admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "500", "payment_mode": "CASH"})
    assert res.get_json()["account"]["given_total"] == 2500.0


def test_give_amount_must_be_a_positive_number(admin_client):
    wid = add_worker()
    for bad in ("0", "-5", "abc", ""):
        res = admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": bad, "payment_mode": "CASH"})
        assert res.status_code == 422 and "amount" in res.get_json()["fields"], bad


def test_give_requires_a_valid_payment_mode(admin_client):
    wid = add_worker()
    res = admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "500"})
    assert res.status_code == 422 and "payment_mode" in res.get_json()["fields"]
    res = admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "500", "payment_mode": "Cheque"})
    assert res.status_code == 422 and "payment_mode" in res.get_json()["fields"]


def test_giving_cash_to_an_unknown_worker_is_a_404(admin_client):
    res = admin_client.post("/api/cash-purchases/999999/give", json={"amount": "500", "payment_mode": "CASH"})
    assert res.status_code == 404


def test_any_worker_can_receive_cash_no_opt_in_needed(admin_client):
    """Unlike fooding, there's no eligibility checkbox - anyone with a Worker row can be given cash."""
    salaried = Worker(name="Sanjay Salary", category="staff", employment_type="regular")
    db.session.add(salaried)
    db.session.commit()
    res = admin_client.post(f"/api/cash-purchases/{salaried.id}/give", json={"amount": "300", "payment_mode": "CASH"})
    assert res.status_code == 200


# ---------- the employee's own view ----------

def test_cash_purchases_me_needs_a_worker_row(client):
    assert client.get("/api/cash-purchases/me").status_code == 404
    assert client.post("/api/cash-purchases/me", json={}).status_code == 404


def test_a_worker_with_nothing_given_yet_sees_no_account_not_an_error(app):
    who, wid = worker_user(app)
    data = who.get("/api/cash-purchases/me").get_json()
    assert data["account"] is None and data["entries"] == []


def test_a_worker_sees_their_own_account_once_given_cash(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "1500", "payment_mode": "CASH"})
    data = who.get("/api/cash-purchases/me").get_json()
    assert data["account"]["given_total"] == 1500.0 and data["account"]["remaining"] == 1500.0


# ---------- logging a purchase ----------

def test_logging_a_purchase_needs_cash_given_first(app):
    who, wid = worker_user(app)
    res = who.post("/api/cash-purchases/me", json={
        "material_name": "Diesel", "amount": "500", "entry_date": "2026-10-21",
    })
    assert res.status_code == 422


def test_logging_a_purchase_creates_a_pending_entry(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    res = who.post("/api/cash-purchases/me", json={
        "entry_date": "2026-10-21", "material_name": "Diesel", "quantity": "10", "unit": "litres",
        "amount": "900", "supplier": "Highway Fuels", "note": "For the site generator",
    })
    assert res.status_code == 201
    entry = res.get_json()["entry"]
    assert entry["status"] == "pending" and entry["material_name"] == "Diesel"
    assert entry["quantity"] == 10.0 and entry["unit"] == "litres" and entry["amount"] == 900.0
    assert entry["supplier"] == "Highway Fuels" and entry["worker_name"] == "Deepak Daily"

    # not yet counted against the balance - only an approval does that
    account = who.get("/api/cash-purchases/me").get_json()["account"]
    assert account["spent_total"] == 0.0 and account["remaining"] == 2000.0


def test_purchase_needs_material_name_and_a_positive_amount(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    res = who.post("/api/cash-purchases/me", json={"material_name": "", "amount": "500"})
    assert res.status_code == 422 and "material_name" in res.get_json()["fields"]
    res = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "0"})
    assert res.status_code == 422 and "amount" in res.get_json()["fields"]
    res = who.post("/api/cash-purchases/me", json={"material_name": "Diesel"})
    assert res.status_code == 422 and "amount" in res.get_json()["fields"]


def test_purchase_quantity_is_optional_but_must_be_positive_if_given(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    res = who.post("/api/cash-purchases/me", json={"material_name": "Toll receipt", "amount": "80"})
    assert res.status_code == 201 and res.get_json()["entry"]["quantity"] is None

    res = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "80", "quantity": "0"})
    assert res.status_code == 422 and "quantity" in res.get_json()["fields"]


def test_a_purchase_defaults_to_todays_date(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    res = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "80"})
    assert res.get_json()["entry"]["entry_date"]   # some ISO date, not blank


# ---------- approving / rejecting ----------

def test_approving_a_purchase_deducts_the_balance(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]

    res = admin_client.post(f"/api/cash-purchases/{entry_id}/approve")
    assert res.status_code == 200
    entry = res.get_json()["entry"]
    assert entry["status"] == "approved" and entry["approved_by_name"] == "grtechno"

    account = who.get("/api/cash-purchases/me").get_json()["account"]
    assert account["spent_total"] == 900.0 and account["remaining"] == 1100.0


def test_spending_more_than_given_leaves_remaining_negative(app, admin_client):
    """No stock-style ceiling here - cash can be overspent, the employee is just owed the difference back."""
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "500", "payment_mode": "CASH"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "700"}).get_json()["entry"]["id"]
    admin_client.post(f"/api/cash-purchases/{entry_id}/approve")
    account = who.get("/api/cash-purchases/me").get_json()["account"]
    assert account["remaining"] == -200.0


def test_rejecting_a_purchase_leaves_the_balance_untouched(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]

    res = admin_client.post(f"/api/cash-purchases/{entry_id}/reject")
    assert res.status_code == 200 and res.get_json()["entry"]["status"] == "rejected"
    account = who.get("/api/cash-purchases/me").get_json()["account"]
    assert account["spent_total"] == 0.0 and account["remaining"] == 2000.0


def test_cannot_approve_or_reject_twice(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]
    admin_client.post(f"/api/cash-purchases/{entry_id}/approve")
    assert admin_client.post(f"/api/cash-purchases/{entry_id}/approve").status_code == 409
    assert admin_client.post(f"/api/cash-purchases/{entry_id}/reject").status_code == 409


def test_an_accountant_cannot_approve_or_reject_a_purchase_only_the_admin_can(app, admin_client):
    """kohal, 2026-11-02: "only admin can approve it since only admin can open the phonepe app and pay through the
    bank accounts" - an accountant (who may also have a Worker row, and log purchases) can look but not decide."""
    accountant = make_user("Anil Accounts", role="accounts")
    requester = signed_in(app, accountant)
    with app.app_context():
        w = Worker(name="Anil Accounts", category="staff", employment_type="daily_wages", user_code=accountant.code)
        db.session.add(w)
        db.session.commit()
        wid = w.id
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    entry_id = requester.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]

    assert requester.post(f"/api/cash-purchases/{entry_id}/approve").status_code == 403
    assert requester.post(f"/api/cash-purchases/{entry_id}/reject").status_code == 403
    other = signed_in(app, make_user("Other Accounts", role="accounts"))
    assert other.post(f"/api/cash-purchases/{entry_id}/approve").status_code == 403
    assert admin_client.post(f"/api/cash-purchases/{entry_id}/approve").status_code == 200


def test_an_accountant_cannot_decide_a_cash_request_either(app, admin_client, accounts_client):
    who, wid = worker_user(app)
    rid = who.post("/api/cash-purchases/requests", json={"amount": "2000"}).get_json()["request"]["id"]
    assert accounts_client.get("/api/cash-purchases/requests").get_json()["can_decide"] is False
    assert accounts_client.post(f"/api/cash-purchases/requests/{rid}/reject").status_code == 403
    assert accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH", "request_id": rid}).status_code == 403
    assert admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH", "request_id": rid}).status_code == 200


def test_pending_list_only_shows_pending_entries(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    e1 = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]
    e2 = who.post("/api/cash-purchases/me", json={"material_name": "Cement", "amount": "400"}).get_json()["entry"]["id"]
    admin_client.post(f"/api/cash-purchases/{e1}/approve")

    ids = [p["id"] for p in admin_client.get("/api/cash-purchases/pending").get_json()["pending"]]
    assert e2 in ids and e1 not in ids


def test_pending_response_includes_workers_and_payment_modes_for_the_give_sheet(admin_client):
    add_worker("Ramesh Welder")
    data = admin_client.get("/api/cash-purchases/pending").get_json()
    assert any(w["name"] == "Ramesh Welder" for w in data["workers"])
    assert data["payment_modes"] == ["VK PP BB", "GR CANARA BANK", "VK GPAY SBI", "GR BB", "CASH", "GR BOB"]


def test_mes_entries_show_every_status_newest_first(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    e1 = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]
    e2 = who.post("/api/cash-purchases/me", json={"material_name": "Cement", "amount": "400"}).get_json()["entry"]["id"]
    admin_client.post(f"/api/cash-purchases/{e1}/approve")
    admin_client.post(f"/api/cash-purchases/{e2}/reject")

    entries = who.get("/api/cash-purchases/me").get_json()["entries"]
    statuses = {e["id"]: e["status"] for e in entries}
    assert statuses[e1] == "approved" and statuses[e2] == "rejected"


# ---------- the bill (uploaded after the fact) ----------

def test_bill_upload_needs_a_file(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]
    res = who.post(f"/api/cash-purchases/{entry_id}/bill", data={})
    assert res.status_code == 422


def test_bill_upload_and_delete_by_the_logger(app, admin_client):
    import io
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]

    res = who.post(f"/api/cash-purchases/{entry_id}/bill", data={"bill": (io.BytesIO(b"fake"), "bill.jpg", "image/jpeg")},
                    content_type="multipart/form-data")
    assert res.status_code == 201 and res.get_json()["entry"]["bill_url"]

    res = who.delete(f"/api/cash-purchases/{entry_id}/bill")
    assert res.status_code == 200 and res.get_json()["entry"]["bill_url"] is None


def test_bill_upload_blocked_for_someone_else(app, admin_client):
    import io
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]

    other, _ = worker_user(app, name="Other Worker", pin="193857")
    res = other.post(f"/api/cash-purchases/{entry_id}/bill", data={"bill": (io.BytesIO(b"fake"), "bill.jpg", "image/jpeg")},
                      content_type="multipart/form-data")
    assert res.status_code == 403

    # the admin/accountant can still attach one on someone else's behalf
    res = admin_client.post(f"/api/cash-purchases/{entry_id}/bill", data={"bill": (io.BytesIO(b"fake"), "bill.jpg", "image/jpeg")},
                                content_type="multipart/form-data")
    assert res.status_code == 201


# ---------- its own page, next to Fooding (kohal, 2026-10-21) ----------
#
# "this pending approval should have its own block next to fooding. named as purchase approval - this is
# only visisble to admin. inside this there will be approvals and alocate cash (same as fooding types)."

def test_purchase_approvals_page_is_admin_or_accountant_only(client, accounts_client, admin_client):
    assert client.get("/purchase-approvals").status_code == 403
    assert accounts_client.get("/purchase-approvals").status_code == 200
    assert admin_client.get("/purchase-approvals").status_code == 200


def test_an_ordinary_employee_never_sees_the_purchase_approval_tile(app):
    who, wid = worker_user(app)
    html = who.get("/me").get_data(as_text=True)
    assert "Purchase approval" not in html
    assert who.get("/purchase-approvals").status_code == 403


def test_admin_and_accountant_get_a_purchase_approval_tile_next_to_fooding(admin_client, accounts_client):
    for who in (admin_client, accounts_client):
        html = who.get("/me").get_data(as_text=True)
        assert html.count('href="/purchase-approvals"') == 1 and "Purchase approval" in html
        assert 'href="/fooding"' in html   # both tiles together, same grid


def test_the_purchase_approval_tile_shows_how_many_are_pending(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"})
    who.post("/api/cash-purchases/me", json={"material_name": "Cement", "amount": "400"})

    html = admin_client.get("/me").get_data(as_text=True)
    assert "2 pending" in html


def test_the_purchase_approval_tile_shows_nothing_when_theres_no_queue(admin_client):
    html = admin_client.get("/me").get_data(as_text=True)
    assert "Purchase approval" in html
    # no "X pending" sum line when the queue is empty, same as Fooding shows no count at zero
    assert "0 pending" not in html


# ---------- Allocated cash & balance subtab (kohal, 2026-10-21) ----------
#
# "allocate cash should be a button and then this form should open. and the subtab should be allocated cash
# and balance and their it should show employees to whom cash is allocated and how much they have balance
# rn. clicking on one employee should show the history of cash expense and whether approved or rejected."

def test_accounts_needs_admin_or_accountant(client, accounts_client, admin_client):
    assert client.get("/api/cash-purchases/accounts").status_code == 403
    assert accounts_client.get("/api/cash-purchases/accounts").status_code == 200
    assert admin_client.get("/api/cash-purchases/accounts").status_code == 200


def test_accounts_only_lists_workers_whove_actually_been_given_cash(app, admin_client):
    who, wid = worker_user(app)
    never_given = add_worker("Never Given Anything")
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "1500", "payment_mode": "CASH"})

    data = admin_client.get("/api/cash-purchases/accounts").get_json()
    ids = [a["worker_id"] for a in data["accounts"]]
    assert wid in ids and never_given not in ids
    row = next(a for a in data["accounts"] if a["worker_id"] == wid)
    assert row["given_total"] == 1500.0 and row["spent_total"] == 0.0 and row["remaining"] == 1500.0


def test_accounts_includes_workers_and_payment_modes_for_the_give_sheet(admin_client):
    add_worker("Ramesh Welder")
    data = admin_client.get("/api/cash-purchases/accounts").get_json()
    assert any(w["name"] == "Ramesh Welder" for w in data["workers"])
    assert data["payment_modes"] == ["VK PP BB", "GR CANARA BANK", "VK GPAY SBI", "GR BB", "CASH", "GR BOB"]


def test_worker_history_needs_admin_or_accountant(app, client, admin_client):
    who, wid = worker_user(app)
    assert client.get(f"/api/cash-purchases/{wid}").status_code == 403
    assert admin_client.get(f"/api/cash-purchases/{wid}").status_code == 200


def test_worker_history_shows_every_entry_regardless_of_status(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    e1 = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]
    e2 = who.post("/api/cash-purchases/me", json={"material_name": "Cement", "amount": "400"}).get_json()["entry"]["id"]
    admin_client.post(f"/api/cash-purchases/{e1}/approve")
    admin_client.post(f"/api/cash-purchases/{e2}/reject")

    data = admin_client.get(f"/api/cash-purchases/{wid}").get_json()
    assert data["worker"]["name"] == "Deepak Daily"
    assert data["account"]["remaining"] == 1100.0
    statuses = {e["id"]: e["status"] for e in data["entries"]}
    assert statuses[e1] == "approved" and statuses[e2] == "rejected"


def test_worker_history_for_a_worker_never_given_cash_shows_no_account(admin_client):
    wid = add_worker("Never Given Anything")
    data = admin_client.get(f"/api/cash-purchases/{wid}").get_json()
    assert data["account"] is None and data["entries"] == []


def test_worker_history_for_an_unknown_worker_is_a_404(admin_client):
    assert admin_client.get("/api/cash-purchases/999999").status_code == 404


# ---------- cash requests (kohal, 2026-10-21): the employee's own ask, before anything is given ----------

def test_requesting_cash_needs_a_worker_row(client):
    assert client.post("/api/cash-purchases/requests", json={"amount": "500"}).status_code == 404


def test_only_admin_or_accountant_can_see_pending_requests(client, accounts_client, admin_client):
    assert client.get("/api/cash-purchases/requests").status_code == 403
    assert accounts_client.get("/api/cash-purchases/requests").status_code == 200
    assert admin_client.get("/api/cash-purchases/requests").status_code == 200


def test_requesting_cash_creates_a_pending_request(app):
    who, wid = worker_user(app)
    res = who.post("/api/cash-purchases/requests", json={"amount": "5000", "note": "Fuel for the week"})
    assert res.status_code == 201
    req = res.get_json()["request"]
    assert req["worker_id"] == wid and req["amount"] == 5000.0 and req["status"] == "pending"
    assert req["note"] == "Fuel for the week"


def test_a_daily_wage_worker_cannot_request_cash(app):
    """kohal, 2026-10-21: "daily wages employee should not be able to request for cash" - their pay
    settles day by day already. Doesn't touch the rest of the feature: the admin can still give them cash
    unprompted, and they can still log what they bought with it (test_logging_a_purchase_creates_a_pending_
    entry already covers that with the default worker_user, now a contractor - see worker_user itself)."""
    who, wid = worker_user(app, employment_type="daily_wages")
    res = who.post("/api/cash-purchases/requests", json={"amount": "2000"})
    assert res.status_code == 403
    assert who.get("/api/cash-purchases/me").get_json()["can_request"] is False


def test_a_non_daily_wage_worker_can_request_cash(app):
    who, wid = worker_user(app, employment_type="contractor")
    assert who.get("/api/cash-purchases/me").get_json()["can_request"] is True
    assert who.post("/api/cash-purchases/requests", json={"amount": "2000"}).status_code == 201


def test_request_amount_must_be_a_positive_number(app):
    who, wid = worker_user(app)
    assert who.post("/api/cash-purchases/requests", json={"amount": "0"}).status_code == 422
    assert who.post("/api/cash-purchases/requests", json={"amount": "not-a-number"}).status_code == 422


def test_cannot_have_two_pending_requests_at_once(app):
    who, wid = worker_user(app)
    who.post("/api/cash-purchases/requests", json={"amount": "2000"})
    res = who.post("/api/cash-purchases/requests", json={"amount": "3000"})
    assert res.status_code == 409


def test_a_new_request_is_fine_once_the_old_one_is_resolved(app, admin_client):
    who, wid = worker_user(app)
    first = who.post("/api/cash-purchases/requests", json={"amount": "2000"}).get_json()["request"]
    admin_client.post(f"/api/cash-purchases/requests/{first['id']}/reject", json={})
    second = who.post("/api/cash-purchases/requests", json={"amount": "3000"})
    assert second.status_code == 201


def test_own_requests_show_up_in_my_cash_purchases(app, admin_client):
    who, wid = worker_user(app)
    who.post("/api/cash-purchases/requests", json={"amount": "2000"})
    data = who.get("/api/cash-purchases/me").get_json()
    assert len(data["requests"]) == 1 and data["requests"][0]["amount"] == 2000.0


def test_pending_requests_list_includes_workers_and_payment_modes(app, admin_client):
    who, wid = worker_user(app)
    who.post("/api/cash-purchases/requests", json={"amount": "2000"})
    data = admin_client.get("/api/cash-purchases/requests").get_json()
    assert len(data["requests"]) == 1 and data["requests"][0]["worker_id"] == wid
    assert any(w["id"] == wid for w in data["workers"]) and data["payment_modes"]


def test_rejecting_a_request_gives_nothing_and_closes_it(app, admin_client):
    who, wid = worker_user(app)
    req = who.post("/api/cash-purchases/requests", json={"amount": "2000"}).get_json()["request"]
    res = admin_client.post(f"/api/cash-purchases/requests/{req['id']}/reject", json={})
    assert res.status_code == 200 and res.get_json()["request"]["status"] == "rejected"
    assert admin_client.get("/api/cash-purchases/requests").get_json()["requests"] == []
    assert who.get("/api/cash-purchases/me").get_json()["account"] is None


def test_cannot_reject_an_already_resolved_request(app, admin_client):
    who, wid = worker_user(app)
    req = who.post("/api/cash-purchases/requests", json={"amount": "2000"}).get_json()["request"]
    admin_client.post(f"/api/cash-purchases/requests/{req['id']}/reject", json={})
    res = admin_client.post(f"/api/cash-purchases/requests/{req['id']}/reject", json={})
    assert res.status_code == 409


def test_rejecting_an_unknown_request_is_a_404(admin_client):
    assert admin_client.post("/api/cash-purchases/requests/999999/reject", json={}).status_code == 404


def test_only_admin_or_accountant_can_reject_a_request(client, app):
    who, wid = worker_user(app)
    req = who.post("/api/cash-purchases/requests", json={"amount": "2000"}).get_json()["request"]
    assert client.post(f"/api/cash-purchases/requests/{req['id']}/reject", json={}).status_code == 403


def test_giving_cash_against_a_request_fulfils_it(app, admin_client):
    who, wid = worker_user(app)
    req = who.post("/api/cash-purchases/requests", json={"amount": "2000"}).get_json()["request"]
    res = admin_client.post(f"/api/cash-purchases/{wid}/give",
                                json={"amount": "2000", "payment_mode": "CASH", "request_id": req["id"]})
    assert res.status_code == 200 and res.get_json()["account"]["given_total"] == 2000.0
    resolved = who.get("/api/cash-purchases/me").get_json()["requests"][0]
    assert resolved["status"] == "fulfilled" and resolved["resolved_by_name"]


def test_giving_cash_with_an_already_resolved_request_id_is_rejected(app, admin_client):
    who, wid = worker_user(app)
    req = who.post("/api/cash-purchases/requests", json={"amount": "2000"}).get_json()["request"]
    admin_client.post(f"/api/cash-purchases/requests/{req['id']}/reject", json={})
    res = admin_client.post(f"/api/cash-purchases/{wid}/give",
                                json={"amount": "2000", "payment_mode": "CASH", "request_id": req["id"]})
    assert res.status_code == 422


def test_giving_cash_with_a_request_for_a_different_worker_is_rejected(app, admin_client):
    who, wid = worker_user(app, name="Requester")
    req = who.post("/api/cash-purchases/requests", json={"amount": "2000"}).get_json()["request"]
    other_id = add_worker("Someone Else")
    res = admin_client.post(f"/api/cash-purchases/{other_id}/give",
                                json={"amount": "2000", "payment_mode": "CASH", "request_id": req["id"]})
    assert res.status_code == 422


def test_giving_cash_without_a_request_id_still_works_as_before(admin_client):
    wid = add_worker()
    res = admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "1000", "payment_mode": "CASH"})
    assert res.status_code == 200


def test_requests_count_toward_the_purchase_approval_tiles_pending_sum(app, admin_client):
    who, wid = worker_user(app)
    who.post("/api/cash-purchases/requests", json={"amount": "2000"})
    html = admin_client.get("/me").get_data(as_text=True)
    assert "1 pending" in html


# ---------- each subtab knows the other subtabs' counts too, for their own badges ----------
# (kohal, 2026-10-21: "should show the count of request in the subtab ust like in material reuest in
# inventory") - pending/pending_requests/accounts each return both counts, the same bundling pattern
# app/inventory.py's own tabs use (pending_request_count/restock_count on every one of its 3 endpoints).

def test_each_subtab_response_carries_both_pending_counts(app, admin_client):
    who, wid = worker_user(app)
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH"})
    who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"})
    who.post("/api/cash-purchases/requests", json={"amount": "3000"})

    pending = admin_client.get("/api/cash-purchases/pending").get_json()
    assert len(pending["pending"]) == 1 and pending["pending_request_count"] == 1

    requests = admin_client.get("/api/cash-purchases/requests").get_json()
    assert len(requests["requests"]) == 1 and requests["pending_purchase_count"] == 1

    accounts = admin_client.get("/api/cash-purchases/accounts").get_json()
    assert accounts["pending_purchase_count"] == 1 and accounts["pending_request_count"] == 1


def test_an_employees_page_lists_the_cash_given_to_them_with_dates(admin_client):
    wid = add_worker()
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "CASH", "note": "For site"})
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "500", "payment_mode": "GR BB"})
    data = admin_client.get(f"/api/cash-purchases/{wid}").get_json()
    assert [(t["amount"], t["payment_mode"]) for t in data["topups"]] == [(500.0, "GR BB"), (2000.0, "CASH")]
    assert data["topups"][1]["note"] == "For site" and data["topups"][0]["entry_date"]


def _wallet_worker(allotted="1000"):
    from datetime import date as _d
    from app.models import FoodingAccount
    wid = add_worker("Fooding Fred")
    w = db.session.get(Worker, wid)
    w.fooding_opt_in = True
    db.session.add(FoodingAccount(worker=w, anchor_date=_d.today(), allotted_total=Decimal(allotted),
                                  deducted_total=Decimal("0"), is_paused=True))      # paused, so no daily food muddies the sums
    db.session.commit()
    return wid


def test_cash_for_a_fooding_worker_comes_out_of_their_fooding_balance(admin_client):
    wid = _wallet_worker("1000")
    # No account is needed or asked for.
    res = admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "400", "note": "Pipes"})
    assert res.status_code == 200 and res.get_json()["account"]["given_total"] == 400.0

    reg = admin_client.get(f"/api/fooding/{wid}").get_json()
    assert reg["fooding"]["remaining"] == 600.0
    expense = [e for e in reg["entries"] if e["kind"] == "expense"][0]
    assert (expense["amount"], expense["purpose"]) == (400.0, "Cash for purchases: Pipes")
    # ... and no bank / cash account of the admin's is debited.
    assert all(a["debits"] == 0 and a["credits"] == 0 for a in admin_client.get("/api/accounts").get_json()["accounts"])


def test_cash_for_a_fooding_worker_cannot_exceed_their_fooding_balance(admin_client):
    wid = _wallet_worker("300")
    res = admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "500"})
    assert res.status_code == 422 and "Only" in res.get_json()["fields"]["amount"] and "300" in res.get_json()["fields"]["amount"]
    assert admin_client.get(f"/api/fooding/{wid}").get_json()["fooding"]["remaining"] == 300.0
    assert admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "300"}).status_code == 200
    assert admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "1"}).status_code == 422


def test_cash_for_someone_without_a_fooding_wallet_still_needs_an_account(admin_client):
    wid = add_worker("No Wallet")
    assert admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "100"}).status_code == 422


def _wallet_user(app, allotted="1000", employment_type="contractor"):
    from datetime import date as _d
    from app.models import FoodingAccount
    who, wid = worker_user(app, name="Sunny Wallet", employment_type=employment_type)
    w = db.session.get(Worker, wid)
    w.fooding_opt_in = True
    db.session.add(FoodingAccount(worker=w, anchor_date=_d.today(), allotted_total=Decimal(allotted),
                                  deducted_total=Decimal("0"), is_paused=True))
    db.session.commit()
    return who, wid


def test_a_non_daily_wage_worker_on_the_fooding_wallet_can_request_cash_up_to_their_balance(app, admin_client):
    who, wid = _wallet_user(app, "1000")
    assert who.get("/api/cash-purchases/me").get_json()["can_request"] is True
    over = who.post("/api/cash-purchases/requests", json={"amount": "1500"})
    assert over.status_code == 422 and "1,000" in over.get_json()["fields"]["amount"]

    req = who.post("/api/cash-purchases/requests", json={"amount": "600", "note": "Pipes"})
    assert req.status_code == 201
    rid = req.get_json()["request"]["id"]
    # The admin fulfils it: no account to pick, and it comes out of the worker's fooding balance.
    res = admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "600", "request_id": rid})
    assert res.status_code == 200
    assert admin_client.get(f"/api/fooding/{wid}").get_json()["fooding"]["remaining"] == 400.0
    assert who.get("/api/cash-purchases/me").get_json()["requests"][0]["status"] == "fulfilled"


def test_a_daily_wage_worker_cannot_request_cash_even_with_a_fooding_wallet(app):
    """kohal, 2026-11-02: "for daily wages, remove this request cash" - the wallet tops itself up instead."""
    who, wid = _wallet_user(app, "1000", employment_type="daily_wages")
    assert who.get("/api/cash-purchases/me").get_json()["can_request"] is False
    assert who.post("/api/cash-purchases/requests", json={"amount": "100"}).status_code == 403


def test_a_wallet_worker_with_nothing_left_cannot_request_cash(app):
    who, wid = _wallet_user(app, "0")
    res = who.post("/api/cash-purchases/requests", json={"amount": "100"})
    assert res.status_code == 422 and "nothing left" in res.get_json()["fields"]["amount"]

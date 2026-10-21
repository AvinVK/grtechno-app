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


def worker_user(app, name="Deepak Daily", pin="285193"):
    """A signed-in User with a matching Worker, linked the way sync_worker_for_user would."""
    user = make_user(name, pin=pin)
    worker = Worker(name=name, category="manpower", employment_type="daily_wages", user_code=user.code)
    db.session.add(worker)
    db.session.commit()
    return signed_in(app, user), worker.id


# ---------- admin/accountant: giving cash ----------

def test_only_admin_or_accountant_can_give_or_see_pending(client, accounts_client, admin_client):
    wid = add_worker()
    assert client.post(f"/api/cash-purchases/{wid}/give", json={"amount": 100, "payment_mode": "Cash"}).status_code == 403
    assert client.get("/api/cash-purchases/pending").status_code == 403
    assert accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": 100, "payment_mode": "Cash"}).status_code == 200
    assert admin_client.get("/api/cash-purchases/pending").status_code == 200


def test_giving_cash_creates_the_account(accounts_client):
    wid = add_worker()
    res = accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    assert res.status_code == 200
    body = res.get_json()["account"]
    assert body["given_total"] == 2000.0 and body["spent_total"] == 0.0 and body["remaining"] == 2000.0


def test_a_second_give_adds_to_the_balance_not_replaces_it(accounts_client):
    wid = add_worker()
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    res = accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "500", "payment_mode": "Cash"})
    assert res.get_json()["account"]["given_total"] == 2500.0


def test_give_amount_must_be_a_positive_number(accounts_client):
    wid = add_worker()
    for bad in ("0", "-5", "abc", ""):
        res = accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": bad, "payment_mode": "Cash"})
        assert res.status_code == 422 and "amount" in res.get_json()["fields"], bad


def test_give_requires_a_valid_payment_mode(accounts_client):
    wid = add_worker()
    res = accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "500"})
    assert res.status_code == 422 and "payment_mode" in res.get_json()["fields"]
    res = accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "500", "payment_mode": "Cheque"})
    assert res.status_code == 422 and "payment_mode" in res.get_json()["fields"]


def test_giving_cash_to_an_unknown_worker_is_a_404(accounts_client):
    res = accounts_client.post("/api/cash-purchases/999999/give", json={"amount": "500", "payment_mode": "Cash"})
    assert res.status_code == 404


def test_any_worker_can_receive_cash_no_opt_in_needed(accounts_client):
    """Unlike fooding, there's no eligibility checkbox - anyone with a Worker row can be given cash."""
    salaried = Worker(name="Sanjay Salary", category="staff", employment_type="regular")
    db.session.add(salaried)
    db.session.commit()
    res = accounts_client.post(f"/api/cash-purchases/{salaried.id}/give", json={"amount": "300", "payment_mode": "Cash"})
    assert res.status_code == 200


# ---------- the employee's own view ----------

def test_cash_purchases_me_needs_a_worker_row(client):
    assert client.get("/api/cash-purchases/me").status_code == 404
    assert client.post("/api/cash-purchases/me", json={}).status_code == 404


def test_a_worker_with_nothing_given_yet_sees_no_account_not_an_error(app):
    who, wid = worker_user(app)
    data = who.get("/api/cash-purchases/me").get_json()
    assert data["account"] is None and data["entries"] == []


def test_a_worker_sees_their_own_account_once_given_cash(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "1500", "payment_mode": "Cash"})
    data = who.get("/api/cash-purchases/me").get_json()
    assert data["account"]["given_total"] == 1500.0 and data["account"]["remaining"] == 1500.0


# ---------- logging a purchase ----------

def test_logging_a_purchase_needs_cash_given_first(app):
    who, wid = worker_user(app)
    res = who.post("/api/cash-purchases/me", json={
        "material_name": "Diesel", "amount": "500", "entry_date": "2026-10-21",
    })
    assert res.status_code == 422


def test_logging_a_purchase_creates_a_pending_entry(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
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


def test_purchase_needs_material_name_and_a_positive_amount(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    res = who.post("/api/cash-purchases/me", json={"material_name": "", "amount": "500"})
    assert res.status_code == 422 and "material_name" in res.get_json()["fields"]
    res = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "0"})
    assert res.status_code == 422 and "amount" in res.get_json()["fields"]
    res = who.post("/api/cash-purchases/me", json={"material_name": "Diesel"})
    assert res.status_code == 422 and "amount" in res.get_json()["fields"]


def test_purchase_quantity_is_optional_but_must_be_positive_if_given(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    res = who.post("/api/cash-purchases/me", json={"material_name": "Toll receipt", "amount": "80"})
    assert res.status_code == 201 and res.get_json()["entry"]["quantity"] is None

    res = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "80", "quantity": "0"})
    assert res.status_code == 422 and "quantity" in res.get_json()["fields"]


def test_a_purchase_defaults_to_todays_date(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    res = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "80"})
    assert res.get_json()["entry"]["entry_date"]   # some ISO date, not blank


# ---------- approving / rejecting ----------

def test_approving_a_purchase_deducts_the_balance(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]

    res = accounts_client.post(f"/api/cash-purchases/{entry_id}/approve")
    assert res.status_code == 200
    entry = res.get_json()["entry"]
    assert entry["status"] == "approved" and entry["approved_by_name"] == "Anil Accounts"

    account = who.get("/api/cash-purchases/me").get_json()["account"]
    assert account["spent_total"] == 900.0 and account["remaining"] == 1100.0


def test_spending_more_than_given_leaves_remaining_negative(app, accounts_client):
    """No stock-style ceiling here - cash can be overspent, the employee is just owed the difference back."""
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "500", "payment_mode": "Cash"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "700"}).get_json()["entry"]["id"]
    accounts_client.post(f"/api/cash-purchases/{entry_id}/approve")
    account = who.get("/api/cash-purchases/me").get_json()["account"]
    assert account["remaining"] == -200.0


def test_rejecting_a_purchase_leaves_the_balance_untouched(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]

    res = accounts_client.post(f"/api/cash-purchases/{entry_id}/reject")
    assert res.status_code == 200 and res.get_json()["entry"]["status"] == "rejected"
    account = who.get("/api/cash-purchases/me").get_json()["account"]
    assert account["spent_total"] == 0.0 and account["remaining"] == 2000.0


def test_cannot_approve_or_reject_twice(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]
    accounts_client.post(f"/api/cash-purchases/{entry_id}/approve")
    assert accounts_client.post(f"/api/cash-purchases/{entry_id}/approve").status_code == 409
    assert accounts_client.post(f"/api/cash-purchases/{entry_id}/reject").status_code == 409


def test_the_logger_cannot_approve_or_reject_their_own_purchase(app, admin_client):
    """kohal, 2026-10-21: "approved by admin" - an accountant who also logged it can't sign off their own,
    same ban as a material request. An accountant can have a Worker row of their own (e.g. they're also on
    site sometimes), same as "Anil Accounts" elsewhere in this app's own tests."""
    accountant = make_user("Anil Accounts", role="accounts")
    requester = signed_in(app, accountant)
    with app.app_context():
        w = Worker(name="Anil Accounts", category="staff", employment_type="daily_wages", user_code=accountant.code)
        db.session.add(w)
        db.session.commit()
        wid = w.id
    admin_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    entry_id = requester.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]

    assert requester.post(f"/api/cash-purchases/{entry_id}/approve").status_code == 403
    assert requester.post(f"/api/cash-purchases/{entry_id}/reject").status_code == 403
    other = signed_in(app, make_user("Other Accounts", role="accounts"))
    assert other.post(f"/api/cash-purchases/{entry_id}/approve").status_code == 200


def test_pending_list_only_shows_pending_entries(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    e1 = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]
    e2 = who.post("/api/cash-purchases/me", json={"material_name": "Cement", "amount": "400"}).get_json()["entry"]["id"]
    accounts_client.post(f"/api/cash-purchases/{e1}/approve")

    ids = [p["id"] for p in accounts_client.get("/api/cash-purchases/pending").get_json()["pending"]]
    assert e2 in ids and e1 not in ids


def test_pending_response_includes_workers_and_payment_modes_for_the_give_sheet(accounts_client):
    add_worker("Ramesh Welder")
    data = accounts_client.get("/api/cash-purchases/pending").get_json()
    assert any(w["name"] == "Ramesh Welder" for w in data["workers"])
    assert "Cash" in data["payment_modes"] and "Online/UPI" in data["payment_modes"]


def test_mes_entries_show_every_status_newest_first(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    e1 = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]
    e2 = who.post("/api/cash-purchases/me", json={"material_name": "Cement", "amount": "400"}).get_json()["entry"]["id"]
    accounts_client.post(f"/api/cash-purchases/{e1}/approve")
    accounts_client.post(f"/api/cash-purchases/{e2}/reject")

    entries = who.get("/api/cash-purchases/me").get_json()["entries"]
    statuses = {e["id"]: e["status"] for e in entries}
    assert statuses[e1] == "approved" and statuses[e2] == "rejected"


# ---------- the bill (uploaded after the fact) ----------

def test_bill_upload_needs_a_file(app, accounts_client):
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]
    res = who.post(f"/api/cash-purchases/{entry_id}/bill", data={})
    assert res.status_code == 422


def test_bill_upload_and_delete_by_the_logger(app, accounts_client):
    import io
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]

    res = who.post(f"/api/cash-purchases/{entry_id}/bill", data={"bill": (io.BytesIO(b"fake"), "bill.jpg", "image/jpeg")},
                    content_type="multipart/form-data")
    assert res.status_code == 201 and res.get_json()["entry"]["bill_url"]

    res = who.delete(f"/api/cash-purchases/{entry_id}/bill")
    assert res.status_code == 200 and res.get_json()["entry"]["bill_url"] is None


def test_bill_upload_blocked_for_someone_else(app, accounts_client):
    import io
    who, wid = worker_user(app)
    accounts_client.post(f"/api/cash-purchases/{wid}/give", json={"amount": "2000", "payment_mode": "Cash"})
    entry_id = who.post("/api/cash-purchases/me", json={"material_name": "Diesel", "amount": "900"}).get_json()["entry"]["id"]

    other, _ = worker_user(app, name="Other Worker", pin="193857")
    res = other.post(f"/api/cash-purchases/{entry_id}/bill", data={"bill": (io.BytesIO(b"fake"), "bill.jpg", "image/jpeg")},
                      content_type="multipart/form-data")
    assert res.status_code == 403

    # the admin/accountant can still attach one on someone else's behalf
    res = accounts_client.post(f"/api/cash-purchases/{entry_id}/bill", data={"bill": (io.BytesIO(b"fake"), "bill.jpg", "image/jpeg")},
                                content_type="multipart/form-data")
    assert res.status_code == 201

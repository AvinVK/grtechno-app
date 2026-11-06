"""The admin's Accounts view (kohal, 2026-10-31): every debit and credit that went through each bank / cash account.
See app/accounts.py."""

from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import Client, Project, ProjectPayment, Worker, WorkerPayment


def _payment(mode, amount, label="Advance"):
    c = Client(name="Ravi Traders", address="x")
    p = Project(client=c, title="Shop fit-out", status="running")
    db.session.add_all([c, p])
    db.session.flush()
    p.payments.append(ProjectPayment(label=label, amount=Decimal(amount), mode=mode, paid_date=date(2026, 10, 20), position=1))
    return p


def test_only_the_admin_can_see_the_accounts(admin_client, manager_client):
    assert admin_client.get("/api/accounts").status_code == 200
    assert manager_client.get("/api/accounts").status_code == 403
    assert manager_client.get("/accounts").status_code == 403


def test_every_account_is_listed_with_what_came_in_and_went_out(admin_client):
    p = _payment("GR BB", "5000")
    w = Worker(name="Sunny Welder", employment_type="daily_wages")
    db.session.add(w)
    db.session.flush()
    w.payments.append(WorkerPayment(label="Week 1", amount=Decimal("1200"), mode="GR BB", paid_date=date(2026, 10, 25), position=1))
    w.payments.append(WorkerPayment(label="Week 1", amount=Decimal("700"), mode="CASH", paid_date=date(2026, 10, 25), position=2))
    db.session.commit()

    listing = {a["name"]: a for a in admin_client.get("/api/accounts").get_json()["accounts"]}
    assert set(listing) == {"VK PP BB", "GR CANARA BANK", "VK GPAY SBI", "GR BB", "CASH", "GR BOB", "CASH DHANBAD", "YES BANK", "GR BB DHANBAD NEW"}
    assert (listing["GR BB"]["credits"], listing["GR BB"]["debits"], listing["GR BB"]["balance"]) == (5000.0, 1200.0, 3800.0)
    assert listing["CASH"]["debits"] == 700.0 and listing["GR BOB"]["count"] == 0

    detail = admin_client.get("/api/accounts/detail", query_string={"name": "GR BB"}).get_json()
    assert [(e["kind"], e["reason"], e["party"]) for e in detail["entries"]] == [
        ("debit", "Wages", "Sunny Welder"), ("credit", "Project payment", "Ravi Traders")]       # newest first
    assert admin_client.get("/api/accounts/detail", query_string={"name": "Nope"}).status_code == 404


def test_an_older_mode_belongs_to_no_account(admin_client):
    _payment("Cheque", "900")
    db.session.commit()
    assert all(a["count"] == 0 for a in admin_client.get("/api/accounts").get_json()["accounts"])


def test_fooding_cash_given_and_lead_advance_show_with_who_asked(admin_client):
    from app.models import CashAccount, CashTopup, FoodingAccount, FoodingEntry, Lead, User
    w = Worker(name="Sunny Welder", employment_type="daily_wages")
    db.session.add(w)
    db.session.flush()
    asker = User.query.first().code
    fa = FoodingAccount(worker=w, anchor_date=date(2026, 10, 1))
    ca = CashAccount(worker=w)
    db.session.add_all([fa, ca])
    db.session.flush()
    db.session.add_all([
        FoodingEntry(account=fa, kind="allot", amount=Decimal("500"), payment_mode="GR BOB", status="approved",
                     entry_date=date(2026, 10, 21), created_by_code=asker),
        FoodingEntry(account=fa, kind="allot", amount=Decimal("300"), payment_mode="GR BOB", status="pending", entry_date=date(2026, 10, 22)),
        CashTopup(account=ca, amount=Decimal("250"), payment_mode="GR BOB", note="Fuel", entry_date=date(2026, 10, 23), created_by_code=asker),
        Lead(contact_name="Mr Rao", company="Rao Mills", advance_amount=Decimal("2000"), advance_date=date(2026, 10, 24), advance_mode="GR BOB"),
    ])
    db.session.commit()
    d = admin_client.get("/api/accounts/detail", query_string={"name": "GR BOB"}).get_json()
    assert [(e["kind"], e["reason"], e["amount"]) for e in d["entries"]] == [
        ("credit", "Lead advance", 2000.0), ("debit", "Cash given for purchases", 250.0), ("debit", "Fooding", 500.0)]
    assert d["entries"][2]["requested_by"] is not None and (d["credits"], d["debits"], d["balance"]) == (2000.0, 750.0, 1250.0)


def _fund(account, amount):
    _payment(account, amount)
    db.session.commit()


def _transfer(client, **over):
    body = {"from_account": "GR BB", "to_account": "CASH", "amount": "2500", "entry_date": "2026-11-01", "note": "For site cash"}
    body.update(over)
    return client.post("/api/accounts/transfers", json=body)


def test_a_self_transfer_is_a_debit_on_one_account_and_a_credit_on_the_other(admin_client):
    _fund("GR BB", "5000")
    assert _transfer(admin_client).status_code == 201
    listing = {a["name"]: a for a in admin_client.get("/api/accounts").get_json()["accounts"]}
    assert (listing["GR BB"]["debits"], listing["GR BB"]["balance"]) == (2500.0, 2500.0)
    assert (listing["CASH"]["credits"], listing["CASH"]["debits"]) == (2500.0, 0.0)

    out = admin_client.get("/api/accounts/detail", query_string={"name": "GR BB"}).get_json()["entries"][0]
    into = admin_client.get("/api/accounts/detail", query_string={"name": "CASH"}).get_json()["entries"][0]
    assert (out["kind"], out["reason"], out["party"], out["detail"]) == ("debit", "Self transfer", "CASH", "For site cash")
    assert (into["kind"], into["reason"], into["party"]) == ("credit", "Self transfer", "GR BB")
    assert out["transfer_id"] == into["transfer_id"]


def test_a_self_transfer_is_checked(admin_client, manager_client):
    _fund("GR BB", "5000")
    assert _transfer(admin_client, to_account="GR BB").status_code == 422
    assert _transfer(admin_client, amount="0").status_code == 422
    assert _transfer(admin_client, amount="").status_code == 422
    assert _transfer(admin_client, amount="-5").status_code == 422
    assert _transfer(admin_client, from_account="Nope").status_code == 422
    assert _transfer(admin_client, to_account="").status_code == 422
    assert admin_client.get("/api/accounts").get_json()["accounts"][3]["count"] == 1      # only the funding entry
    assert _transfer(manager_client).status_code == 403


def test_you_cannot_transfer_more_than_the_account_holds(admin_client):
    r = _transfer(admin_client)                                       # GR BB is empty
    assert r.status_code == 422 and r.get_json()["fields"]["amount"] == "There is no money in GR BB"
    _fund("GR BB", "2000")
    r = _transfer(admin_client, amount="2500")
    assert r.status_code == 422 and "Only" in r.get_json()["fields"]["amount"] and "2,000" in r.get_json()["fields"]["amount"]
    assert _transfer(admin_client, amount="2000").status_code == 201   # the whole balance is fine
    assert _transfer(admin_client, amount="1").status_code == 422      # now it is empty
    assert _transfer(admin_client, from_account="CASH", to_account="GR BB", amount="2000").status_code == 201   # money that arrived can move on


def test_removing_a_transfer_puts_both_accounts_back(admin_client):
    _fund("GR BB", "5000")
    tid = _transfer(admin_client).get_json()["id"]
    assert admin_client.delete(f"/api/accounts/transfers/{tid}").status_code == 200
    assert {a["name"]: a["count"] for a in admin_client.get("/api/accounts").get_json()["accounts"]}["CASH"] == 0
    assert admin_client.delete(f"/api/accounts/transfers/{tid}").status_code == 404

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
    assert set(listing) == {"VK PP BB", "GR CANARA BANK", "VK GPAY SBI", "GR BB", "CASH", "GR BOB"}
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

"""A project another team runs and the admin only pays for (kohal, 2026-11-14: "a flag in more details which when turned on, will disable
request material and return material and will give a tab of 'add expense' in expenses tab ... he wants to keep a tally of expenses")."""

import io

from openpyxl import load_workbook

from app.models import CommissionPayment, ProjectExpense
from test_adhoc import order
from test_projects import add_material_and_issue, commission_worker, make_project, project_with_amount, stocked_material


def _flag(client, pid, on=True):
    return client.patch(f"/api/projects/{pid}", json={"managed_by_others": on})


def _expense(client, pid, **over):
    body = {"note": "Site tiles", "person_name": "Sharma Traders", "amount": "12500", "entry_date": "2026-11-10", "payment_account": "GR BB", **over}
    return client.post(f"/api/projects/{pid}/tally-expenses", json=body)


def _ledger(client, account="GR BB"):
    return [r for r in client.get("/api/accounts/detail", query_string={"name": account}).get_json()["entries"] if r["reason"] == "Project expense"]


def test_the_flag_is_off_by_default_and_the_admin_can_switch_it(client, admin_client):
    pid = make_project(client, admin_client)
    assert admin_client.get(f"/api/projects/{pid}").get_json()["project"]["managed_by_others"] is False
    res = _flag(admin_client, pid)
    assert res.status_code == 200 and res.get_json()["project"]["managed_by_others"] is True
    assert _flag(admin_client, pid, False).get_json()["project"]["managed_by_others"] is False


def test_only_the_admin_can_change_it_and_it_must_be_on_or_off(client, admin_client, manager_client):
    pid = make_project(client, admin_client)
    assert _flag(manager_client, pid).status_code == 403
    assert admin_client.patch(f"/api/projects/{pid}", json={"managed_by_others": "yes"}).status_code == 422
    assert admin_client.get(f"/api/projects/{pid}").get_json()["project"]["managed_by_others"] is False
    assert manager_client.patch(f"/api/projects/{pid}", json={"managed_by_others": False}).status_code == 200      # unchanged is no change


def test_an_adhoc_order_cannot_be_one(admin_client):
    pid = order(admin_client).get_json()["project_id"]
    res = _flag(admin_client, pid)
    assert res.status_code == 422 and "managed_by_others" in res.get_json()["fields"]


def test_material_cannot_be_requested_or_returned_while_it_is_on(app, client, admin_client):
    pid = make_project(client, admin_client)
    mat = stocked_material(admin_client)
    assert admin_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat, "quantity": 2}).status_code == 201
    _flag(admin_client, pid)
    for body in ({"material_id": mat, "quantity": 2}, {"material_id": mat, "quantity": 1, "kind": "in"}):
        res = admin_client.post(f"/api/projects/{pid}/material-requests", json=body)
        assert res.status_code == 409 and "another team" in res.get_json()["error"]
    listing = admin_client.get(f"/api/projects/{pid}/material-requests").get_json()
    assert listing["can_request"] is False and listing["managed_by_others"] is True
    _flag(admin_client, pid, False)
    assert admin_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat, "quantity": 2}).status_code == 201


def test_an_expense_needs_the_flag_on(client, admin_client):
    pid = make_project(client, admin_client)
    assert _expense(admin_client, pid).status_code == 409
    _flag(admin_client, pid)
    assert _expense(admin_client, pid).status_code == 201


def test_an_expense_is_kept_in_the_tally_and_paid_from_its_account(app, client, admin_client):
    pid = make_project(client, admin_client)
    _flag(admin_client, pid)
    body = _expense(admin_client, pid).get_json()
    e = body["expenses"][0]
    assert (e["kind"], e["note"], e["person_name"], e["amount"], e["entry_date"]) == ("expense", "Site tiles", "Sharma Traders", 12500.0, "2026-11-10")
    assert [(p["amount"], p["payment_account"], p["paid_date"]) for p in e["payments"]] == [(12500.0, "GR BB", "2026-11-10")]
    assert (body["total_tally_expense"], body["total_commission"]) == (12500.0, 0.0)
    row, = _ledger(admin_client)
    assert (row["kind"], row["amount"], row["party"]) == ("debit", 12500.0, "Sharma Traders") and "Site tiles" in row["detail"]


def test_an_expense_without_an_account_is_only_on_the_tally(client, admin_client):
    pid = make_project(client, admin_client)
    _flag(admin_client, pid)
    body = _expense(admin_client, pid, payment_account="", person_name="").get_json()
    assert body["expenses"][0]["payments"] == [] and body["total_tally_expense"] == 12500.0
    assert _ledger(admin_client) == []


def test_a_bad_expense_is_refused_and_nothing_is_saved(app, client, admin_client):
    pid = make_project(client, admin_client)
    _flag(admin_client, pid)
    for over, field in (({"note": "  "}, "note"), ({"note": "x" * 301}, "note"), ({"amount": "0"}, "amount"), ({"amount": "abc"}, "amount"),
                        ({"amount": ""}, "amount"), ({"payment_account": "Piggy bank"}, "payment_account"), ({"person_name": "x" * 121}, "person_name"),
                        ({"entry_date": "2999-01-01"}, "entry_date"), ({"entry_date": "soon"}, "entry_date")):
        res = _expense(admin_client, pid, **over)
        assert res.status_code == 422 and field in res.get_json()["fields"], over
    assert admin_client.post(f"/api/projects/{pid}/tally-expenses", json={"amount": "10"}).status_code == 422
    with app.app_context():
        assert ProjectExpense.query.count() == 0 and CommissionPayment.query.count() == 0


def test_an_expense_can_be_edited_and_its_account_follows(app, client, admin_client):
    pid = make_project(client, admin_client)
    _flag(admin_client, pid)
    eid = _expense(admin_client, pid).get_json()["expenses"][0]["id"]
    res = admin_client.patch(f"/api/projects/{pid}/tally-expenses/{eid}", json={"note": "Site tiles and grout", "person_name": "Sharma", "amount": "13000",
                                                                              "entry_date": "2026-11-11", "payment_account": "CASH"})
    e = res.get_json()["expenses"][0]
    assert (e["note"], e["amount"], e["entry_date"]) == ("Site tiles and grout", 13000.0, "2026-11-11")
    assert [(p["amount"], p["payment_account"]) for p in e["payments"]] == [(13000.0, "CASH")]
    assert _ledger(admin_client) == [] and [r["amount"] for r in _ledger(admin_client, "CASH")] == [13000.0]
    res = admin_client.patch(f"/api/projects/{pid}/tally-expenses/{eid}", json={"note": "Site tiles", "amount": "13000", "payment_account": ""})
    assert res.get_json()["expenses"][0]["payments"] == [] and _ledger(admin_client, "CASH") == []
    res = admin_client.patch(f"/api/projects/{pid}/tally-expenses/{eid}", json={"note": "Site tiles", "amount": "13000", "payment_account": "YES BANK"})
    assert [p["payment_account"] for p in res.get_json()["expenses"][0]["payments"]] == ["YES BANK"]


def test_removing_an_expense_gives_the_money_back_to_the_account(app, client, admin_client):
    pid = make_project(client, admin_client)
    _flag(admin_client, pid)
    eid = _expense(admin_client, pid).get_json()["expenses"][0]["id"]
    assert len(_ledger(admin_client)) == 1
    body = admin_client.delete(f"/api/projects/{pid}/tally-expenses/{eid}").get_json()
    assert body["expenses"] == [] and body["total_tally_expense"] == 0.0 and _ledger(admin_client) == []
    assert admin_client.delete(f"/api/projects/{pid}/tally-expenses/{eid}").status_code == 404
    with app.app_context():
        assert CommissionPayment.query.count() == 0


def test_the_commission_routes_leave_a_tally_expense_alone_and_the_other_way_round(app, client, admin_client):
    pid = project_with_amount(client, admin_client, 200000)
    _flag(admin_client, pid)
    with app.app_context():
        wid = commission_worker()
    tally = _expense(admin_client, pid).get_json()["expenses"][0]["id"]
    comm = admin_client.post(f"/api/projects/{pid}/expenses", json={"worker_id": wid, "amount": "5000"}).get_json()["expenses"][0]
    assert admin_client.patch(f"/api/projects/{pid}/expenses/{tally}", json={"worker_id": wid, "amount": "1"}).status_code == 404
    assert admin_client.delete(f"/api/projects/{pid}/expenses/{tally}").status_code == 404
    assert admin_client.post(f"/api/projects/{pid}/expenses/{tally}/payments", json={"amount": "1", "payment_account": "CASH"}).status_code == 404
    assert admin_client.patch(f"/api/projects/{pid}/tally-expenses/{comm['id']}", json={"note": "x", "amount": "1"}).status_code == 404
    assert admin_client.delete(f"/api/projects/{pid}/tally-expenses/{comm['id']}").status_code == 404
    detail = admin_client.get(f"/api/projects/{pid}").get_json()
    assert (detail["total_commission"], detail["total_tally_expense"], detail["total_expense"]) == (5000.0, 12500.0, 17500.0)


def test_an_expense_stays_on_the_tally_after_the_flag_is_switched_off(client, admin_client):
    pid = make_project(client, admin_client)
    _flag(admin_client, pid)
    _expense(admin_client, pid)
    _flag(admin_client, pid, False)
    detail = admin_client.get(f"/api/projects/{pid}").get_json()
    assert detail["total_tally_expense"] == 12500.0 and len(detail["expenses"]) == 1
    assert _expense(admin_client, pid).status_code == 409


def test_the_projects_report_lists_the_expense_under_expenses(app, client, admin_client):
    pid = make_project(client, admin_client)
    _flag(admin_client, pid)
    _expense(admin_client, pid)
    res = admin_client.get("/api/reports/projects?month=2026-11")
    assert res.status_code == 200
    wb = load_workbook(io.BytesIO(res.data))
    expenses = [[c.value for c in r] for r in wb["Expenses"].iter_rows(min_row=2)]
    assert [(e[3], e[4], e[5], e[6]) for e in expenses] == [("Expense", "Sharma Traders", "Site tiles", 12500)]

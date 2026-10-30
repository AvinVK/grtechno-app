"""Adhoc clients (kohal, 2026-10-30): supply or refilling of extinguishers, one project per order, the contact
number identifying the admin_client. See app/adhoc.py."""

from app.extensions import db
from app.models import AdhocItem, Client, Project

REFILL = {"fe_type": "ABC 4 kg", "weight": "4 kg", "qty": 3, "rate": "450", "refill_date": "2026-10-20",
          "hpt_date": "2026-09-01", "expiry_date": "2027-10-20", "remark": "Dented"}
SUPPLY = {"fe_type": "CO2", "weight": "4.5 kg", "qty": 2, "rate": "3200.50"}


def order(admin_client, **over):
    body = {"name": "Ravi Traders", "address": "Shop 4, Sitabuldi", "phone": "98765 43210",
            "service": "refilling", "items": [REFILL], **over}
    return admin_client.post("/api/adhoc/orders", json=body)


def test_a_new_adhoc_client_and_its_project_are_created_together(admin_client):
    res = order(admin_client)
    assert res.status_code == 201, res.get_json()
    body = res.get_json()
    c = db.session.get(Client, body["client_id"])
    assert c.is_adhoc and c.name == "Ravi Traders" and c.phone == "9876543210" and c.address == "Shop 4, Sitabuldi"
    p = db.session.get(Project, body["project_id"])
    assert p.client_id == c.id and p.status == "unbilled" and p.service_names == ["Refilling of fire extinguishers"]
    assert float(p.estimated_amount) == 1350.0                     # 3 x 450
    item = p.adhoc_items[0]
    assert item.qty == 3 and item.refill_date.isoformat() == "2026-10-20" and item.expiry_date.isoformat() == "2027-10-20"


def test_supply_has_no_refill_dates_and_the_value_is_qty_times_rate(admin_client):
    res = order(admin_client, service="supply", items=[SUPPLY, {**SUPPLY, "fe_type": "Fire blanket", "qty": 1, "rate": 800}])
    assert res.status_code == 201
    p = db.session.get(Project, res.get_json()["project_id"])
    assert p.service_names == ["Supply of extinguishers"]
    assert float(p.estimated_amount) == 2 * 3200.50 + 800
    assert [i.refill_date for i in p.adhoc_items] == [None, None]


def test_the_contact_number_is_the_key_so_a_repeat_goes_through_the_existing_client(admin_client):
    first = order(admin_client).get_json()
    dup = order(admin_client, phone="+91 9876543210")
    assert dup.status_code == 422 and "phone" in dup.get_json()["fields"]
    again = admin_client.post("/api/adhoc/orders", json={"client_id": first["client_id"], "service": "supply", "items": [SUPPLY]})
    assert again.status_code == 201 and again.get_json()["client_id"] == first["client_id"]
    assert Client.query.filter_by(is_adhoc=True).count() == 1
    assert len(db.session.get(Client, first["client_id"]).projects) == 2


def test_the_form_is_checked_field_by_field(admin_client):
    bad = admin_client.post("/api/adhoc/orders", json={"name": "", "address": "", "phone": "123", "service": "installation", "items": []})
    assert bad.status_code == 422
    fields = bad.get_json()["fields"]
    assert {"name", "address", "phone", "service", "items"} <= set(fields)
    badline = order(admin_client, items=[{"fe_type": "", "weight": "", "qty": 0, "rate": "x"}])
    f = badline.get_json()["fields"]
    assert {"items.0.fe_type", "items.0.weight", "items.0.qty", "items.0.rate"} <= set(f)
    reversed_dates = order(admin_client, items=[{**REFILL, "expiry_date": "2026-01-01"}])
    assert "items.0.expiry_date" in reversed_dates.get_json()["fields"]
    no_dates = order(admin_client, items=[{"fe_type": "ABC", "weight": "4 kg", "qty": 1, "rate": 100}])      # refilling: dates are required too
    assert {"items.0.refill_date", "items.0.hpt_date", "items.0.expiry_date"} <= set(no_dates.get_json()["fields"])
    assert Client.query.count() == 0                               # nothing was half-created
    no_remark = order(admin_client, items=[{k: v for k, v in REFILL.items() if k != "remark"}])             # ...but the remark is not
    assert no_remark.status_code == 201


def test_existing_adhoc_clients_are_listed_for_choosing(admin_client):
    order(admin_client)
    data = admin_client.get("/api/adhoc/clients").get_json()
    assert [(c["name"], c["phone"], c["orders"]) for c in data["clients"]] == [("Ravi Traders", "9876543210", 1)]
    assert [s["key"] for s in data["services"]] == ["supply", "refilling"]


def test_items_can_be_edited_and_added_to_and_the_value_follows(admin_client):
    pid = order(admin_client).get_json()["project_id"]
    res = admin_client.put(f"/api/adhoc/projects/{pid}/items", json={"items": [REFILL, {**REFILL, "fe_type": "DCP 9 kg", "qty": 1, "rate": 900}]})
    assert res.status_code == 200 and res.get_json()["estimated_amount"] == 1350.0 + 900.0
    assert AdhocItem.query.filter_by(project_id=pid).count() == 2
    assert admin_client.put(f"/api/adhoc/projects/{pid}/items", json={"items": []}).status_code == 422


def test_a_normal_project_is_not_an_adhoc_one(admin_client):
    c = Client(name="Normal Co")
    db.session.add(c)
    db.session.flush()
    p = Project(client=c, title="Install", site_name="Plant")
    db.session.add(p)
    db.session.commit()
    assert admin_client.put(f"/api/adhoc/projects/{p.id}/items", json={"items": [SUPPLY]}).status_code == 404


def test_adhoc_clients_stay_out_of_the_normal_client_pickers(admin_client):
    order(admin_client)
    normal = Client(name="Normal Co")
    db.session.add(normal)
    db.session.commit()
    names = [c["name"] for c in admin_client.get("/api/projects/options").get_json()["clients"]] if admin_client.get("/api/projects/options").status_code == 200 else None
    if names is not None:
        assert "Ravi Traders" not in names and "Normal Co" in names
    # An adhoc customer is not a client: only the normal one is on the Clients list.
    listing = admin_client.get("/api/clients").get_json()["clients"]
    assert {c["name"]: c["is_adhoc"] for c in listing} == {"Normal Co": False}


def test_project_detail_marks_an_adhoc_project_and_carries_its_items(admin_client):
    pid = order(admin_client).get_json()["project_id"]
    detail = admin_client.get(f"/api/projects/{pid}").get_json()
    assert detail["project"]["is_adhoc"] is True and detail["adhoc_kind"] == "refilling"
    assert detail["project"]["adhoc_items"][0]["amount"] == 1350.0


def test_only_people_with_clients_or_projects_can_use_it(client):
    """The plain test user (field sales) has neither module."""
    assert client.get("/api/adhoc/clients").status_code == 403
    assert client.post("/api/adhoc/orders", json={}).status_code == 403


# ---------- materials for an adhoc project, from inventory (kohal, 2026-10-30) ----------

def _stock_item(name="ABC 4 kg"):
    from app.models import Material
    from sqlalchemy import func
    m = Material.query.filter(func.lower(Material.name) == name.lower()).first()
    if m is None:
        m = Material(name=name, is_active=True)
        db.session.add(m)
    m.avg_rate, m.stock_qty = 100, 5
    db.session.commit()
    return m.id


def test_only_admin_project_manager_or_accountant_can_request_material_for_an_adhoc_project(app, admin_client, manager_client, accounts_client):
    from conftest import make_user, signed_in
    pid = order(admin_client).get_json()["project_id"]
    mid = _stock_item()
    body = {"material_id": mid, "quantity": 2}
    ok = admin_client.post(f"/api/projects/{pid}/material-requests", json=body)
    assert ok.status_code == 201, ok.get_json()
    assert manager_client.post(f"/api/projects/{pid}/material-requests", json=body).status_code in (201, 404)   # a manager sees it if it is theirs
    director = signed_in(app, make_user("Dee Director", role="company_director"))
    assert director.get(f"/api/projects/{pid}/material-requests").get_json()["can_request"] is False
    assert director.post(f"/api/projects/{pid}/material-requests", json=body).status_code == 403
    assert admin_client.get(f"/api/projects/{pid}/material-requests").get_json()["can_request"] is True


def test_the_request_form_gets_the_orders_items_to_choose_from(admin_client):
    pid = order(admin_client).get_json()["project_id"]
    items = admin_client.get(f"/api/projects/{pid}/material-requests").get_json()["adhoc_items"]
    assert [(i["fe_type"], i["qty"]) for i in items] == [("ABC 4 kg", 3)]


def test_a_normal_project_is_unchanged_anyone_who_can_see_it_may_request(admin_client):
    c = Client(name="Normal Co")
    db.session.add(c)
    db.session.flush()
    p = Project(client=c, title="Install", site_name="Plant")
    db.session.add(p)
    db.session.commit()
    data = admin_client.get(f"/api/projects/{p.id}/material-requests").get_json()
    assert data["can_request"] is True and data["adhoc_items"] == []


def test_nobody_is_offered_an_adhoc_project_at_check_in(app):
    from conftest import make_user, signed_in
    order(signed_in(app, make_user("Admin Two", is_admin=True)))
    who = signed_in(app, make_user("Plain Staff", role="helper"))
    assert who.get("/api/attendance/state").get_json()["projects"] == []


def test_the_projects_list_marks_adhoc_ones_so_they_get_their_own_subtab(admin_client):
    order(admin_client)
    normal = Client(name="Normal Co")
    db.session.add(normal)
    db.session.flush()
    db.session.add(Project(client=normal, title="Install", site_name="Plant"))
    db.session.commit()
    kinds = {p["title"]: p["is_adhoc"] for p in admin_client.get("/api/projects").get_json()["projects"]}
    assert sorted(kinds.values()) == [False, True]


def test_an_adhoc_project_can_only_ask_for_the_items_on_its_own_order(admin_client):
    pid = order(admin_client).get_json()["project_id"]
    other = _stock_item("Cement")
    assert admin_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": other, "quantity": 1}).status_code == 422
    assert admin_client.post(f"/api/projects/{pid}/material-requests", json={"material_name": "Anything else", "quantity": 1}).status_code == 422
    # The order's own item by name, even when it is not stocked yet: allowed, and added to inventory for restock.
    ok = admin_client.post(f"/api/projects/{pid}/material-requests", json={"material_name": "abc 4 kg", "quantity": 3})
    assert ok.status_code == 201, ok.get_json()
    from app.models import Material
    assert Material.query.filter_by(name="ABC 4 kg").count() == 1 and float(Material.query.filter_by(name="ABC 4 kg").one().stock_qty) == 0


# ---------- unbilled -> billed (kohal, 2026-10-31) ----------

def _asked(pid):
    from app.models import MaterialMovement
    return MaterialMovement.query.filter_by(project_id=pid, kind="out", requested=True).all()


def test_saving_an_order_starts_unbilled_and_requests_every_item_from_inventory(admin_client):
    pid = order(admin_client, service="supply", items=[SUPPLY, {**SUPPLY, "qty": 3}, {**SUPPLY, "fe_type": "Fire blanket", "qty": 1}]).get_json()["project_id"]
    assert db.session.get(Project, pid).status == "unbilled"
    got = {m.material.name: (float(m.quantity), m.status) for m in _asked(pid)}
    assert got == {"CO2": (5.0, "pending"), "Fire blanket": (1.0, "pending")}      # the two CO2 lines are one request


def test_the_project_is_billed_and_closed_once_its_stock_is_issued(admin_client):
    from app.adhoc import refresh_billing
    pid = order(admin_client).get_json()["project_id"]
    p = db.session.get(Project, pid)
    refresh_billing(p)
    assert p.status == "unbilled"                                   # still waiting on the request
    mv = _asked(pid)[0]
    mv.status = "approved"
    refresh_billing(p)
    assert p.status == "billed" and p.completed_at is not None


def test_a_shortfall_keeps_it_unbilled_until_the_rest_is_issued(admin_client):
    from app.adhoc import refresh_billing
    from app.models import MaterialMovement
    pid = order(admin_client).get_json()["project_id"]
    p = db.session.get(Project, pid)
    first = _asked(pid)[0]
    first.status = "approved"
    rest = MaterialMovement(material=first.material, kind="out", quantity=1, rate=0, amount=0, project_id=pid,
                            entry_date=first.entry_date, requested=True, status="pending")
    db.session.add(rest)
    db.session.commit()
    refresh_billing(p)
    assert p.status == "unbilled"
    rest.status = "rejected"
    refresh_billing(p)
    assert p.status == "billed"

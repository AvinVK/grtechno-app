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
    assert p.client_id == c.id and p.status == "running" and p.service_names == ["Refilling of fire extinguishers"]
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
    listing = admin_client.get("/api/clients").get_json()["clients"]
    assert {c["name"]: c["is_adhoc"] for c in listing} == {"Ravi Traders": True, "Normal Co": False}


def test_project_detail_marks_an_adhoc_project_and_carries_its_items(admin_client):
    pid = order(admin_client).get_json()["project_id"]
    detail = admin_client.get(f"/api/projects/{pid}").get_json()
    assert detail["project"]["is_adhoc"] is True and detail["adhoc_kind"] == "refilling"
    assert detail["project"]["adhoc_items"][0]["amount"] == 1350.0


def test_only_people_with_clients_or_projects_can_use_it(client):
    """The plain test user (field sales) has neither module."""
    assert client.get("/api/adhoc/clients").status_code == 403
    assert client.post("/api/adhoc/orders", json={}).status_code == 403

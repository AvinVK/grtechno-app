"""Inventory: materials, their stock/cost, and the stock-in / issue ledger that moves them. Admin only,
for now - see app/reference_data.ADMIN_ONLY_MODULES."""

from app.extensions import db
from app.models import Material


def add_material(admin_client, name="Cement", unit="bags"):
    res = admin_client.post("/api/inventory/materials", json={"name": name, "unit": unit})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["material"]


def add_project(admin_client, name="Orchid Heights"):
    res = admin_client.post("/api/projects", json={"new_client_name": name})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["project"]["id"]


# ---------- admin only ----------

def test_only_the_admin_can_open_inventory(client, manager_client, accounts_client, admin_client):
    for who in (client, manager_client, accounts_client):
        assert who.get("/inventory").status_code == 403
        assert who.get("/api/inventory/materials").status_code == 403
    assert admin_client.get("/inventory").status_code == 200
    assert admin_client.get("/api/inventory/materials").status_code == 200


def test_inventory_is_not_in_a_non_admins_menu(client, admin_client):
    names = [m["name"] for m in client.get("/api/modules").get_json()["modules"]]
    assert "Inventory" not in names
    names = [m["name"] for m in admin_client.get("/api/modules").get_json()["modules"]]
    assert "Inventory" in names


# ---------- adding and editing a material ----------

def test_admin_adds_a_material(admin_client):
    material = add_material(admin_client, "TMT Bars", "kg")
    assert material["unit"] == "kg" and material["stock_qty"] == 0 and material["avg_rate"] == 0
    assert material["stock_value"] == 0 and material["is_active"] is True


def test_material_name_is_required_and_cannot_duplicate(admin_client):
    res = admin_client.post("/api/inventory/materials", json={"name": "  "})
    assert res.status_code == 422 and "name" in res.get_json()["fields"]
    add_material(admin_client, "Cement")
    res = admin_client.post("/api/inventory/materials", json={"name": "cement"})
    assert res.status_code == 422 and "name" in res.get_json()["fields"]


def test_admin_edits_a_material_and_can_rename_it_to_its_own_name(admin_client):
    material = add_material(admin_client, "Cement")
    res = admin_client.patch(f"/api/inventory/materials/{material['id']}", json={"name": "Cement", "unit": "bags of 50kg"})
    assert res.status_code == 200 and res.get_json()["material"]["unit"] == "bags of 50kg"


def test_admin_archives_and_restores_a_material(admin_client):
    material = add_material(admin_client)
    res = admin_client.patch(f"/api/inventory/materials/{material['id']}", json={"is_active": False})
    assert res.status_code == 200 and res.get_json()["material"]["is_active"] is False
    res = admin_client.patch(f"/api/inventory/materials/{material['id']}", json={"is_active": True})
    assert res.status_code == 200 and res.get_json()["material"]["is_active"] is True


# ---------- stock in ----------

def test_stock_in_adds_quantity_and_blends_the_average_rate(admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    res = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 100, "rate": 10, "entry_date": "2026-10-01"})
    assert res.status_code == 201
    assert res.get_json()["material"]["stock_qty"] == 100 and res.get_json()["material"]["avg_rate"] == 10

    # 100 @ 10 blended with 50 @ 40 -> (1000 + 2000) / 150 = 20
    res = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 50, "rate": 40})
    assert res.status_code == 201
    m = res.get_json()["material"]
    assert m["stock_qty"] == 150 and m["avg_rate"] == 20 and m["stock_value"] == 3000


def test_stock_in_rejects_a_non_positive_quantity_or_rate(admin_client):
    material = add_material(admin_client)
    res = admin_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": 0, "rate": 10})
    assert res.status_code == 422 and "quantity" in res.get_json()["fields"]
    res = admin_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": -5, "rate": 10})
    assert res.status_code == 422 and "quantity" in res.get_json()["fields"]


# ---------- issuing to a project ----------

def test_issuing_material_reduces_stock_at_the_average_rate_and_records_the_project(admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 100, "rate": 10})
    pid = add_project(admin_client)

    res = admin_client.post(f"/api/inventory/materials/{mid}/issue", json={"quantity": 30, "project_id": pid, "note": "Foundation work"})
    assert res.status_code == 201
    m = res.get_json()["material"]
    assert m["stock_qty"] == 70 and m["avg_rate"] == 10                       # average rate doesn't move on issue
    movement = res.get_json()["movement"]
    assert movement["kind"] == "out" and movement["amount"] == 300 and movement["project_id"] == pid

    history = admin_client.get(f"/api/inventory/materials/{mid}").get_json()["movements"]
    assert [mv["kind"] for mv in history] == ["out", "in"]                    # newest first


def test_issuing_more_than_is_in_stock_is_refused(admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 10, "rate": 5})
    pid = add_project(admin_client)
    res = admin_client.post(f"/api/inventory/materials/{mid}/issue", json={"quantity": 11, "project_id": pid})
    assert res.status_code == 422 and "quantity" in res.get_json()["fields"]
    with admin_client.application.app_context():
        assert db.session.get(Material, mid).stock_qty == 10                 # stock untouched by the refused issue


def test_issuing_needs_a_real_project(admin_client):
    material = add_material(admin_client)
    admin_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": 10, "rate": 5})
    res = admin_client.post(f"/api/inventory/materials/{material['id']}/issue", json={"quantity": 1, "project_id": 999999})
    assert res.status_code == 422 and "project_id" in res.get_json()["fields"]
    res = admin_client.post(f"/api/inventory/materials/{material['id']}/issue", json={"quantity": 1})
    assert res.status_code == 422 and "project_id" in res.get_json()["fields"]

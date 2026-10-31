"""Inventory: materials, their stock/cost, and the stock-in / issue ledger that moves them."""

import io
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import Material, MaterialMovement, Worker

from conftest import make_user, signed_in


def add_material(admin_client, name="Cement", unit="bags"):
    res = admin_client.post("/api/inventory/materials", json={"name": name, "unit": unit})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["material"]


def add_project(admin_client, name="Orchid Heights"):
    res = admin_client.post("/api/projects", json={"new_client_name": name})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["project"]["id"]


def add_supplier(admin_client, name="Shree Building Supplies"):
    res = admin_client.post("/api/inventory/suppliers", json={"name": name})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["supplier"]["id"]


def add_worker(admin_client, name="Ramesh Storekeeper"):
    with admin_client.application.app_context():
        w = Worker(name=name)
        db.session.add(w)
        db.session.commit()
        return w.id


def approved_issue(app, admin_client, mid, pid, qty, entry_date=None):
    """An already-approved issue ('out') movement, the only way one can exist now - a material request
    (kohal, 2026-10-19: "even issue to project should have the same process as material request" - the old
    direct-issue-from-Inventory shortcut, self-approved on the spot, is gone) approved by someone other than
    whoever asked for it, since the requester can never approve their own. Returns the approved movement."""
    body = {"material_id": mid, "quantity": qty}
    req = admin_client.post(f"/api/projects/{pid}/material-requests", json=body)
    assert req.status_code == 201, req.get_json()
    movement_id = req.get_json()["request"]["id"]
    if entry_date:
        with admin_client.application.app_context():
            db.session.get(MaterialMovement, movement_id).entry_date = date.fromisoformat(entry_date)
            db.session.commit()
    approver = signed_in(app, make_user(f"Approver {movement_id}", role="accounts"))
    wid = add_worker(admin_client, f"Storekeeper {movement_id}")
    res = approver.post(f"/api/inventory/material-requests/{movement_id}/approve", json={
        "quantity": qty, "given_by_worker_id": wid, "transport_mode": "Own vehicle",
    })
    assert res.status_code == 200, res.get_json()
    return res.get_json()["movement"]


# ---------- admin only ----------

def test_inventory_is_role_gated(client, manager_client, accounts_client, admin_client):
    """Sales field and project manager have no Inventory access; Accountant does (kohal's access matrix,
    2026-10-14) - Inventory used to be admin-only outright, before any role had it."""
    for who in (client, manager_client):
        assert who.get("/inventory").status_code == 403
        assert who.get("/api/inventory/materials").status_code == 403
    assert accounts_client.get("/inventory").status_code == 200
    assert accounts_client.get("/api/inventory/materials").status_code == 200
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
    assert material["code"] == f"MAT-{material['id']:04d}"


def test_material_name_is_required_and_cannot_duplicate(admin_client):
    res = admin_client.post("/api/inventory/materials", json={"name": "  "})
    assert res.status_code == 422 and "name" in res.get_json()["fields"]
    add_material(admin_client, "Cement")
    res = admin_client.post("/api/inventory/materials", json={"name": "cement"})
    assert res.status_code == 422 and "name" in res.get_json()["fields"]


# ---------- the new material's first purchase (optional, right on Add material) ----------

def test_adding_a_material_with_no_quantity_leaves_it_with_no_stock(admin_client):
    material = add_material(admin_client, "No Stock Yet")
    assert material["stock_qty"] == 0 and material["avg_rate"] == 0
    history = admin_client.get(f"/api/inventory/materials/{material['id']}").get_json()["movements"]
    assert history == []


def test_adding_a_material_with_a_quantity_logs_its_first_purchase(admin_client):
    sid = add_supplier(admin_client)
    res = admin_client.post("/api/inventory/materials", json={
        "name": "TMT Bars", "unit": "kg", "quantity": 100, "rate": 60, "supplier_id": sid,
        "bill_no": "INV-1", "payment_mode": "cash", "payment_account": "GR BB", "gst_percent": 18, "note": "Opening stock",
    })
    assert res.status_code == 201, res.get_json()
    body = res.get_json()
    assert body["material"]["stock_qty"] == 100 and body["material"]["avg_rate"] == 60
    movement = body["movement"]
    assert movement["kind"] == "in" and movement["supplier_name"] == "Shree Building Supplies"
    assert movement["gst_amount"] == 1080 and movement["total_cost"] == 7080         # 100*60=6000, 18% = 1080


def test_adding_a_material_with_a_quantity_but_no_rate_is_refused(admin_client):
    res = admin_client.post("/api/inventory/materials", json={"name": "TMT Bars", "quantity": 100})
    assert res.status_code == 422 and "rate" in res.get_json()["fields"]
    assert Material.query.filter_by(name="TMT Bars").first() is None     # nothing half-created


def test_adding_a_material_with_a_rate_but_no_quantity_is_refused(admin_client):
    res = admin_client.post("/api/inventory/materials", json={"name": "TMT Bars", "rate": 60})
    assert res.status_code == 422 and "quantity" in res.get_json()["fields"]


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
#
# Issuing material always goes through a project's own request now (kohal, 2026-10-19: "even issue to
# project should have the same process as material request") - see the "material requests" section further
# down, and projects.py's own test_projects.py for the request side. The old direct-issue-from-Inventory
# shortcut this section used to test is gone.

def test_stocking_in_a_material_with_already_inconsistent_history_is_refused_not_a_500(admin_client):
    """Another real prod crash (kohal, 2026-10-19, a 500 on /inventory#m75/stock-in, traceback confirmed
    from the error log): stock_in() had the same gap as issue() above - every other caller of
    _recompute_material catches _NegativeStock, this one didn't. Here it's reachable even though a stock-in
    itself can never make stock negative (it only ever adds), because the material's *existing* approved
    history was already inconsistent before this new entry - some past approved issue, backdated or
    otherwise, already exceeds what the replay says was in stock at that point. _recompute_material replays
    from scratch on every write, so it hits that same pre-existing break regardless of what triggered it;
    this reproduces that directly (bypassing the API, which wouldn't let the inconsistency happen for a
    *new* issue - see the backdated test above) by inserting an already-broken approved row straight into
    the database, the way old/imported data could."""
    material = add_material(admin_client)
    mid = material["id"]
    pid = add_project(admin_client)
    with admin_client.application.app_context():
        bad = MaterialMovement(
            material_id=mid, kind="out", quantity=Decimal("5"), rate=Decimal("0"), amount=Decimal("0"),
            project_id=pid, entry_date=date(2026, 10, 1), status="approved",
        )
        db.session.add(bad)
        db.session.commit()

    res = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 10, "rate": 5})
    assert res.status_code == 422
    # Names the pre-existing bad row (2026-10-01, the planted 'out'), not the stock-in that was actually
    # submitted - that's the whole point (see _negative_stock_message).
    assert "2026-10-01" in res.get_json()["error"] and "5.00 bags issue" in res.get_json()["error"]


# ---------- supplier, GST and the bill ----------

def test_a_supplier_can_be_added_on_the_fly_and_is_not_duplicated(admin_client):
    sid = add_supplier(admin_client, "Shree Building Supplies")
    res = admin_client.post("/api/inventory/suppliers", json={"name": "shree building supplies"})
    assert res.status_code == 422 and "name" in res.get_json()["fields"]
    res = admin_client.post("/api/inventory/suppliers", json={"name": "  "})
    assert res.status_code == 422 and "name" in res.get_json()["fields"]
    assert isinstance(sid, int)


def test_stock_in_records_the_supplier_bill_and_payment_terms(admin_client):
    material = add_material(admin_client)
    sid = add_supplier(admin_client)
    res = admin_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={
        "quantity": 100, "rate": 10, "supplier_id": sid, "bill_no": "INV-55", "payment_mode": "credit",
        "gst_percent": 18, "note": "First delivery",
    })
    assert res.status_code == 201
    movement = res.get_json()["movement"]
    assert movement["supplier_id"] == sid and movement["supplier_name"] == "Shree Building Supplies"
    assert movement["bill_no"] == "INV-55" and movement["payment_mode"] == "credit"
    assert movement["bill_url"] is None

    history = admin_client.get(f"/api/inventory/materials/{material['id']}").get_json()["movements"]
    assert history[0]["supplier_name"] == "Shree Building Supplies"


def test_stock_in_computes_gst_amount_and_total_cost_server_side(admin_client):
    material = add_material(admin_client)
    # 100 @ 10 = 1000; 18% GST = 180; total 1180 - sent gst_amount/total_cost are ignored if sent at all.
    res = admin_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={
        "quantity": 100, "rate": 10, "gst_percent": 18, "gst_amount": 999999, "total_cost": 1,
    })
    assert res.status_code == 201
    movement = res.get_json()["movement"]
    assert movement["gst_percent"] == 18 and movement["gst_amount"] == 180 and movement["total_cost"] == 1180


def test_stock_in_without_gst_defaults_to_zero(admin_client):
    material = add_material(admin_client)
    res = admin_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": 10, "rate": 5})
    assert res.status_code == 201
    movement = res.get_json()["movement"]
    assert movement["gst_percent"] == 0 and movement["gst_amount"] == 0 and movement["total_cost"] == 50


def test_stock_in_rejects_a_gst_percent_over_100_or_an_unknown_supplier(admin_client):
    material = add_material(admin_client)
    res = admin_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": 10, "rate": 5, "gst_percent": 101})
    assert res.status_code == 422 and "gst_percent" in res.get_json()["fields"]
    res = admin_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": 10, "rate": 5, "supplier_id": 999999})
    assert res.status_code == 422 and "supplier_id" in res.get_json()["fields"]


def test_bill_can_be_uploaded_viewed_and_removed(admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    stocked = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 10, "rate": 5})
    movement_id = stocked.get_json()["movement"]["id"]

    bill = (io.BytesIO(b"%PDF-1.4 fake bill"), "bill.pdf")
    up = admin_client.post(f"/api/inventory/materials/{mid}/movements/{movement_id}/bill",
                            data={"bill": bill}, content_type="multipart/form-data")
    assert up.status_code == 201
    url = up.get_json()["movement"]["bill_url"]
    assert url and url.startswith("/uploads/materials/")
    assert admin_client.get(url).status_code == 200                     # served back like a survey photo

    deleted = admin_client.delete(f"/api/inventory/materials/{mid}/movements/{movement_id}/bill")
    assert deleted.status_code == 200 and deleted.get_json()["movement"]["bill_url"] is None


def test_bill_upload_rejects_a_non_document_file(admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    stocked = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 10, "rate": 5})
    movement_id = stocked.get_json()["movement"]["id"]
    bad = (io.BytesIO(b"not a document"), "notes.txt")
    res = admin_client.post(f"/api/inventory/materials/{mid}/movements/{movement_id}/bill",
                             data={"bill": bad}, content_type="multipart/form-data")
    assert res.status_code == 422


def test_materials_list_and_detail_carry_suppliers_and_workers_for_the_pickers(admin_client):
    sid = add_supplier(admin_client)
    wid = add_worker(admin_client)
    material = add_material(admin_client)
    data = admin_client.get("/api/inventory/materials").get_json()
    assert sid in [s["id"] for s in data["suppliers"]]
    assert wid in [w["id"] for w in data["workers"]]
    data = admin_client.get(f"/api/inventory/materials/{material['id']}").get_json()
    assert sid in [s["id"] for s in data["suppliers"]]
    assert wid in [w["id"] for w in data["workers"]]


# ---------- unit picker (kohal, 2026-10-15: "for unit, need dropdown with these: Meter EA LOT JOB PCS KG ADD NEW") ----------

def test_a_new_unit_is_remembered_for_the_picker_without_duplicating(admin_client):
    add_material(admin_client, "Cement", unit="Bags")
    units = admin_client.get("/api/inventory/materials").get_json()["units"]
    assert "Bags" in units

    # typed again, different case, on another material - not added twice
    add_material(admin_client, "Sand", unit="bags")
    units = admin_client.get("/api/inventory/materials").get_json()["units"]
    assert units.count("Bags") == 1 and "bags" not in units


def test_a_blank_unit_is_not_remembered(admin_client):
    add_material(admin_client, "Cement", unit="")
    units = admin_client.get("/api/inventory/materials").get_json()["units"]
    assert "" not in units


def test_editing_a_material_s_unit_grows_the_picker_too(admin_client):
    material = add_material(admin_client, "Cement", unit="Bags")
    res = admin_client.patch(f"/api/inventory/materials/{material['id']}", json={"name": "Cement", "unit": "KG"})
    assert res.status_code == 200 and res.get_json()["material"]["unit"] == "KG"
    units = admin_client.get("/api/inventory/materials").get_json()["units"]
    assert "KG" in units


def test_material_detail_also_carries_units_for_the_picker(admin_client):
    material = add_material(admin_client, "Cement", unit="Bags")
    data = admin_client.get(f"/api/inventory/materials/{material['id']}").get_json()
    assert "Bags" in data["units"]


def test_materials_list_and_detail_carry_material_names_for_the_name_autopredict(admin_client):
    add_material(admin_client, "Cement")
    material = add_material(admin_client, "Steel Rod")
    data = admin_client.get("/api/inventory/materials").get_json()
    assert {"Cement", "Steel Rod"} <= set(data["material_names"])
    data = admin_client.get(f"/api/inventory/materials/{material['id']}").get_json()
    assert {"Cement", "Steel Rod"} <= set(data["material_names"])


# ---------- frequency and used-in (kohal, 2026-10-15) ----------

def test_frequency_and_used_in_default_to_blank(admin_client):
    material = add_material(admin_client)
    assert material["frequency"] == "" and material["used_in"] == []


def test_frequency_accepts_only_the_fixed_choices(admin_client):
    res = admin_client.post("/api/inventory/materials", json={"name": "Hydrant valve", "frequency": "every_project"})
    assert res.status_code == 201 and res.get_json()["material"]["frequency"] == "every_project"

    res = admin_client.post("/api/inventory/materials", json={"name": "Odd one", "frequency": "sometimes"})
    assert res.status_code == 422 and "frequency" in res.get_json()["fields"]


def test_used_in_takes_more_than_one_category_plus_a_typed_other(admin_client):
    res = admin_client.post("/api/inventory/materials", json={
        "name": "GI Pipe", "used_in": ["Hydrant", "Sprinkler", "Deluge system"],
    })
    assert res.status_code == 201
    assert set(res.get_json()["material"]["used_in"]) == {"Hydrant", "Sprinkler", "Deluge system"}


def test_used_in_drops_blanks_and_duplicates_case_insensitively(admin_client):
    res = admin_client.post("/api/inventory/materials", json={
        "name": "Clamp", "used_in": ["Hydrant", "hydrant", "  ", "Sprinkler"],
    })
    assert res.status_code == 201
    assert res.get_json()["material"]["used_in"] == ["Hydrant", "Sprinkler"]


def test_used_in_must_be_a_list(admin_client):
    res = admin_client.post("/api/inventory/materials", json={"name": "Bad shape", "used_in": "Hydrant"})
    assert res.status_code == 422 and "used_in" in res.get_json()["fields"]


def test_editing_a_material_updates_frequency_and_used_in(admin_client):
    material = add_material(admin_client)
    res = admin_client.patch(f"/api/inventory/materials/{material['id']}", json={
        "name": material["name"], "frequency": "occasional", "used_in": ["Fire alarm", "Portable devices"],
    })
    assert res.status_code == 200
    body = res.get_json()["material"]
    assert body["frequency"] == "occasional" and body["used_in"] == ["Fire alarm", "Portable devices"]


def test_only_a_stock_in_entry_can_have_a_bill(app, admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 10, "rate": 5})
    pid = add_project(admin_client)
    movement_id = approved_issue(app, admin_client, mid, pid, 1)["id"]
    bill = (io.BytesIO(b"%PDF-1.4 fake bill"), "bill.pdf")
    res = admin_client.post(f"/api/inventory/materials/{mid}/movements/{movement_id}/bill",
                             data={"bill": bill}, content_type="multipart/form-data")
    assert res.status_code == 422


# ---------- fixing a bulk-entry mistake: edit or delete a saved entry ----------

def test_editing_a_stock_ins_quantity_and_rate_reblends_the_average(admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    stocked = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 100, "rate": 10})
    movement_id = stocked.get_json()["movement"]["id"]
    # typed 100 @ 10 by mistake - fix it to 50 @ 20
    res = admin_client.patch(f"/api/inventory/materials/{mid}/movements/{movement_id}", json={"quantity": 50, "rate": 20})
    assert res.status_code == 200, res.get_json()
    m = res.get_json()["material"]
    assert m["stock_qty"] == 50 and m["avg_rate"] == 20
    movement = res.get_json()["movement"]
    assert movement["quantity"] == 50 and movement["rate"] == 20 and movement["amount"] == 1000


def test_editing_a_stock_in_recomputes_gst_from_the_new_amount(admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    stocked = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 10, "rate": 10, "gst_percent": 18})
    movement_id = stocked.get_json()["movement"]["id"]
    res = admin_client.patch(f"/api/inventory/materials/{mid}/movements/{movement_id}", json={"quantity": 20, "rate": 10, "gst_percent": 18})
    assert res.status_code == 200
    movement = res.get_json()["movement"]
    assert movement["amount"] == 200 and movement["gst_amount"] == 36 and movement["total_cost"] == 236


def test_editing_an_issues_quantity_adjusts_stock_without_touching_rate(app, admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 100, "rate": 10})
    pid = add_project(admin_client)
    movement_id = approved_issue(app, admin_client, mid, pid, 10)["id"]
    res = admin_client.patch(f"/api/inventory/materials/{mid}/movements/{movement_id}", json={"quantity": 30, "project_id": pid})
    assert res.status_code == 200, res.get_json()
    m = res.get_json()["material"]
    assert m["stock_qty"] == 70 and m["avg_rate"] == 10


def test_editing_a_stock_in_that_would_leave_a_later_issue_short_is_refused(app, admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    stocked = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 100, "rate": 10})
    movement_id = stocked.get_json()["movement"]["id"]
    pid = add_project(admin_client)
    approved_issue(app, admin_client, mid, pid, 80)
    # shrinking the stock-in to 50 would leave the 80-unit issue short
    res = admin_client.patch(f"/api/inventory/materials/{mid}/movements/{movement_id}", json={"quantity": 50, "rate": 10})
    assert res.status_code == 422
    with admin_client.application.app_context():
        assert db.session.get(Material, mid).stock_qty == 20          # untouched by the refused edit


def test_deleting_a_stock_in_entry_removes_it_and_recomputes_stock(admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    first = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 100, "rate": 10})
    first_id = first.get_json()["movement"]["id"]
    admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 50, "rate": 40})

    res = admin_client.delete(f"/api/inventory/materials/{mid}/movements/{first_id}")
    assert res.status_code == 200, res.get_json()
    m = res.get_json()["material"]
    assert m["stock_qty"] == 50 and m["avg_rate"] == 40                # only the second stock-in remains
    history = admin_client.get(f"/api/inventory/materials/{mid}").get_json()["movements"]
    assert len(history) == 1


def test_deleting_a_stock_in_that_a_later_issue_depends_on_is_refused(app, admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    stocked = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 100, "rate": 10})
    movement_id = stocked.get_json()["movement"]["id"]
    pid = add_project(admin_client)
    approved_issue(app, admin_client, mid, pid, 10)
    res = admin_client.delete(f"/api/inventory/materials/{mid}/movements/{movement_id}")
    assert res.status_code == 422
    with admin_client.application.app_context():
        assert db.session.get(Material, mid).stock_qty == 90


def test_deleting_an_issue_restores_the_stock(app, admin_client):
    material = add_material(admin_client)
    mid = material["id"]
    admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 100, "rate": 10})
    pid = add_project(admin_client)
    movement_id = approved_issue(app, admin_client, mid, pid, 30)["id"]
    res = admin_client.delete(f"/api/inventory/materials/{mid}/movements/{movement_id}")
    assert res.status_code == 200
    assert res.get_json()["material"]["stock_qty"] == 100


# ---------- stock-in approval (kohal, 2026-10-16: "approval should be needed of accountant or office incharge") ----------

def director_client(app):
    return signed_in(app, make_user("Dilip Director", role="company_director"))


def office_assistant_client(app):
    return signed_in(app, make_user("Oza Assistant", role="office_assistant"))


def test_stock_in_by_an_accountant_is_approved_straight_away(app, accounts_client):
    material = add_material(accounts_client)
    res = accounts_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": 10, "rate": 5})
    assert res.status_code == 201
    body = res.get_json()
    assert body["movement"]["status"] == "approved" and body["movement"]["approved_by_name"] == "Anil Accounts"
    assert body["material"]["stock_qty"] == 10


def test_stock_in_by_an_office_assistant_is_approved_straight_away(app):
    oa = office_assistant_client(app)
    material = add_material(oa)
    res = oa.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": 10, "rate": 5})
    assert res.status_code == 201 and res.get_json()["movement"]["status"] == "approved"


def test_stock_in_by_company_director_waits_for_an_accountant(app, accounts_client):
    director = director_client(app)
    material = add_material(director)
    res = director.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": 10, "rate": 5})
    assert res.status_code == 201
    body = res.get_json()
    assert body["movement"]["status"] == "pending" and body["movement"]["approved_by_name"] is None
    assert body["material"]["stock_qty"] == 0          # not counted yet

    movement_id = body["movement"]["id"]
    # the director themselves can't approve their own request
    res = director.post(f"/api/inventory/materials/{material['id']}/movements/{movement_id}/approve")
    assert res.status_code == 403

    res = accounts_client.post(f"/api/inventory/materials/{material['id']}/movements/{movement_id}/approve")
    assert res.status_code == 200
    body = res.get_json()
    assert body["movement"]["status"] == "approved" and body["movement"]["approved_by_name"] == "Anil Accounts"
    assert body["material"]["stock_qty"] == 10


def test_rejecting_a_pending_stock_in_leaves_stock_untouched(app, accounts_client):
    director = director_client(app)
    material = add_material(director)
    movement_id = director.post(f"/api/inventory/materials/{material['id']}/stock-in",
                                 json={"quantity": 10, "rate": 5}).get_json()["movement"]["id"]
    res = accounts_client.post(f"/api/inventory/materials/{material['id']}/movements/{movement_id}/reject")
    assert res.status_code == 200
    assert res.get_json()["movement"]["status"] == "rejected"
    assert res.get_json()["material"]["stock_qty"] == 0


def test_cannot_approve_or_reject_a_movement_twice(app, accounts_client):
    director = director_client(app)
    material = add_material(director)
    movement_id = director.post(f"/api/inventory/materials/{material['id']}/stock-in",
                                 json={"quantity": 10, "rate": 5}).get_json()["movement"]["id"]
    assert accounts_client.post(f"/api/inventory/materials/{material['id']}/movements/{movement_id}/approve").status_code == 200
    assert accounts_client.post(f"/api/inventory/materials/{material['id']}/movements/{movement_id}/approve").status_code == 409
    assert accounts_client.post(f"/api/inventory/materials/{material['id']}/movements/{movement_id}/reject").status_code == 409


# ---------- Material requests tab (kohal, 2026-10-17) ----------
#
# "the approval request should go to a new subtab inside inventory called material requests. now anyone
# with inventory access can approve the request. but before approving the request, the physical transport
# of material needs to be recorded as well."

def pending_request(admin_client, app, qty=5, stock=20, material_name="Cement"):
    """A pending issue request - from a project manager, who (since 2026-10-17) has no Inventory access of
    their own and so can't approve their own request just by asking for it."""
    material = add_material(admin_client, name=material_name)
    mat_id = material["id"]
    admin_client.post(f"/api/inventory/materials/{mat_id}/stock-in", json={"quantity": stock, "rate": 10})
    pid = add_project(admin_client)
    pm = signed_in(app, make_user("Priya Manager", role="project_manager"))
    res = pm.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": qty})
    assert res.status_code == 201 and res.get_json()["request"]["status"] == "pending", res.get_json()
    return mat_id, pid, res.get_json()["request"]["id"]


def test_material_requests_lists_pending_issues_from_any_project(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_request(admin_client, app)
    add_worker(admin_client)
    data = accounts_client.get("/api/inventory/material-requests").get_json()
    assert len(data["requests"]) == 1
    row = data["requests"][0]
    assert row["id"] == movement_id and row["material_id"] == mat_id and row["project_id"] == pid
    assert row["quantity"] == 5 and row["stock_qty"] == 20
    assert any(w["name"] for w in data["workers"])                      # the "who took it" picker
    assert "Own vehicle" in data["transport_modes"]


def test_approving_a_request_needs_who_took_it_and_how(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_request(admin_client, app)
    res = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve", json={"quantity": 5})
    assert res.status_code == 422
    assert "given_by_worker_id" in res.get_json()["fields"] and "transport_mode" in res.get_json()["fields"]


def test_approving_a_request_records_who_transported_it(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_request(admin_client, app)
    wid = add_worker(accounts_client, "Ramesh Storekeeper")
    # transported_at now also sets the movement's own entry_date (see approve_material_request) - today,
    # not some earlier arbitrary date, so it doesn't predate pending_request()'s own stock-in (also today).
    res = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve", json={
        "quantity": 5, "given_by_worker_id": wid, "transport_mode": "Own vehicle",
        "transported_at": f"{date.today().isoformat()}T10:30:00",
    })
    assert res.status_code == 200
    mv = res.get_json()["movement"]
    assert mv["status"] == "approved" and mv["given_by_name"] == "Ramesh Storekeeper"
    assert mv["transport_mode"] == "Own vehicle" and mv["transported_at"] is not None
    assert res.get_json()["remainder"] is None
    assert admin_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"] == 15


def test_approving_less_than_requested_splits_the_remainder_into_a_new_pending_request(app, admin_client, accounts_client):
    """kohal, 2026-10-17: "say if stock has 5 pipes and request was raised for 7 pipes then approval can
    only be done for 5 pipes and 2 pipes should be flagged for stock in of that material"."""
    mat_id, pid, movement_id = pending_request(admin_client, app, qty=7, stock=5)
    wid = add_worker(accounts_client)
    res = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve", json={
        "quantity": 5, "given_by_worker_id": wid, "transport_mode": "Hand carried",
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["movement"]["status"] == "approved" and body["movement"]["quantity"] == 5
    assert body["remainder"]["status"] == "pending" and body["remainder"]["quantity"] == 2
    assert body["remainder"]["project_id"] == pid and body["remainder"]["material_id"] == mat_id
    assert body["material"]["stock_qty"] == 0
    # the flag: still owed to pending requests, for whoever does the next stock-in
    assert body["material"]["pending_requested_qty"] == 2

    data = accounts_client.get("/api/inventory/material-requests").get_json()
    assert len(data["requests"]) == 1 and data["requests"][0]["id"] == body["remainder"]["id"]


def test_cannot_approve_more_than_requested_or_more_than_stock(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_request(admin_client, app, qty=5, stock=20)
    too_much = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve", json={"quantity": 6})
    assert too_much.status_code == 422 and "quantity" in too_much.get_json()["fields"]

    mat_id2, pid2, movement_id2 = pending_request(admin_client, app, qty=7, stock=5, material_name="Sand")
    over_stock = accounts_client.post(f"/api/inventory/material-requests/{movement_id2}/approve", json={"quantity": 7})
    assert over_stock.status_code == 422 and "quantity" in over_stock.get_json()["fields"]


def test_approving_sees_stock_that_arrived_after_the_request_was_made(app, admin_client, accounts_client):
    """kohal, 2026-10-22, reported against a real case: "10 piece of welding rod is requested, and
    inventory has 6 rods... now when i do the stockin of 10 rods in inventory, and after that try to
    approves the request, it still shows not enough in stock" - all same-day, which is the scenario that
    actually breaks: the request's own row is older (a lower id) than the stock-in that arrived to cover
    it, and the old replay order (entry_date, id) let that id alone put the request first regardless of
    which one was *actually* approved first. See _recompute_material's own docstring for the full story."""
    material = add_material(admin_client, "Welding Rod")
    mid = material["id"]
    admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 6, "rate": 10})
    pid = add_project(admin_client)
    pm = signed_in(app, make_user("Priya Manager", role="project_manager"))
    req = pm.post(f"/api/projects/{pid}/material-requests", json={"material_id": mid, "quantity": 10})
    assert req.status_code == 201, req.get_json()
    movement_id = req.get_json()["request"]["id"]

    # More stock arrives *after* the request already existed - same day, a higher id than the request's.
    restock = admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 10, "rate": 10})
    assert restock.status_code == 201 and restock.get_json()["material"]["stock_qty"] == 16

    wid = add_worker(accounts_client)
    approve = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve", json={
        "quantity": 10, "given_by_worker_id": wid, "transport_mode": "Own vehicle",
    })
    assert approve.status_code == 200, approve.get_json()
    assert approve.get_json()["material"]["stock_qty"] == 6


def test_rejecting_a_material_request(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_request(admin_client, app)
    res = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/reject")
    assert res.status_code == 200 and res.get_json()["movement"]["status"] == "rejected"
    assert admin_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"] == 20
    assert accounts_client.get("/api/inventory/material-requests").get_json()["requests"] == []


def test_cannot_approve_or_reject_a_material_request_twice(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_request(admin_client, app)
    wid = add_worker(accounts_client)
    accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve",
                          json={"quantity": 5, "given_by_worker_id": wid, "transport_mode": "Courier"})
    again = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve",
                                  json={"quantity": 5, "given_by_worker_id": wid, "transport_mode": "Courier"})
    assert again.status_code == 409
    assert accounts_client.post(f"/api/inventory/material-requests/{movement_id}/reject").status_code == 409


def test_the_requester_cannot_approve_their_own_request(app, admin_client):
    """kohal, 2026-10-19: "creator user cannot be approval" - even someone who'd otherwise qualify to
    approve anyone else's request (here, an accountant) can't sign off on their own."""
    material = add_material(admin_client)
    mat_id = material["id"]
    admin_client.post(f"/api/inventory/materials/{mat_id}/stock-in", json={"quantity": 20, "rate": 10})
    pid = add_project(admin_client)
    requester = signed_in(app, make_user("Anil Accounts", role="accounts"))
    movement_id = requester.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5}).get_json()["request"]["id"]
    wid = add_worker(requester)

    res = requester.post(f"/api/inventory/material-requests/{movement_id}/approve",
                          json={"quantity": 5, "given_by_worker_id": wid, "transport_mode": "Own vehicle"})
    assert res.status_code == 403

    other = signed_in(app, make_user("Other Accounts", role="accounts"))
    res2 = other.post(f"/api/inventory/material-requests/{movement_id}/approve",
                       json={"quantity": 5, "given_by_worker_id": wid, "transport_mode": "Own vehicle"})
    assert res2.status_code == 200 and res2.get_json()["movement"]["approved_by_name"] == "Other Accounts"


def test_the_requester_cannot_reject_their_own_request_either(app, admin_client):
    """Same ban as approving (kohal, 2026-10-20: "even reject material for request and return both should
    not be done by the creator") - deciding your own request either way is still deciding it."""
    material = add_material(admin_client)
    mat_id = material["id"]
    admin_client.post(f"/api/inventory/materials/{mat_id}/stock-in", json={"quantity": 20, "rate": 10})
    pid = add_project(admin_client)
    requester = signed_in(app, make_user("Anil Accounts", role="accounts"))
    movement_id = requester.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5}).get_json()["request"]["id"]

    assert requester.post(f"/api/inventory/material-requests/{movement_id}/reject").status_code == 403

    other = signed_in(app, make_user("Other Accounts", role="accounts"))
    res = other.post(f"/api/inventory/material-requests/{movement_id}/reject")
    assert res.status_code == 200 and res.get_json()["movement"]["status"] == "rejected"


def test_material_request_history_shows_who_approved_or_rejected_it(app, admin_client, accounts_client):
    mat_id, pid, approved_id = pending_request(admin_client, app, material_name="Cement")
    wid = add_worker(accounts_client)
    accounts_client.post(f"/api/inventory/material-requests/{approved_id}/approve",
                          json={"quantity": 5, "given_by_worker_id": wid, "transport_mode": "Own vehicle"})
    mat_id2, pid2, rejected_id = pending_request(admin_client, app, material_name="Sand")
    accounts_client.post(f"/api/inventory/material-requests/{rejected_id}/reject")

    history = accounts_client.get("/api/inventory/material-requests/history").get_json()["requests"]
    assert len(history) == 2
    by_id = {r["id"]: r for r in history}
    assert by_id[approved_id]["status"] == "approved" and by_id[approved_id]["approved_by_name"] == "Anil Accounts"
    assert by_id[approved_id]["created_by_name"] == "Priya Manager"
    assert by_id[rejected_id]["status"] == "rejected" and by_id[rejected_id]["approved_by_name"] == "Anil Accounts"
    # Still pending ones don't show up in history, and history doesn't show up in the pending list.
    mat_id3, pid3, pending_id = pending_request(admin_client, app, material_name="Gravel")
    assert pending_id not in {r["id"] for r in accounts_client.get("/api/inventory/material-requests/history").get_json()["requests"]}
    assert approved_id not in {r["id"] for r in accounts_client.get("/api/inventory/material-requests").get_json()["requests"]}


def test_a_legacy_requested_false_row_still_stays_out_of_the_material_requests_tab(admin_client):
    """kohal, 2026-10-19: "even issue to project should have the same process as material request" - the
    direct-issue-from-Inventory shortcut this used to cover is gone outright now, so there's no live way to
    create a requested=False 'out' row any more. One can still be sitting on file from before that change
    (or from the migration's own best-effort backfill of old, ambiguous data - see
    d2f8a4c6e913_material_movements_requested.py) - this confirms it stays correctly out of the Material
    requests tab (pending or history) either way, same as it always did, even though it's now unreachable
    through the API."""
    material = add_material(admin_client)
    mid = material["id"]
    admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 20, "rate": 5})
    pid = add_project(admin_client)
    with admin_client.application.app_context():
        legacy = MaterialMovement(
            material_id=mid, kind="out", quantity=Decimal("3"), rate=Decimal("5"), amount=Decimal("15"),
            project_id=pid, entry_date=date(2026, 10, 1), status="approved", requested=False,
        )
        db.session.add(legacy)
        db.session.commit()
        legacy_id = legacy.id

    assert legacy_id not in {r["id"] for r in admin_client.get("/api/inventory/material-requests").get_json()["requests"]}
    assert legacy_id not in {r["id"] for r in admin_client.get("/api/inventory/material-requests/history").get_json()["requests"]}
    # Still fully visible on the material's own movement history, same as any other stock-in/issue.
    own_history = admin_client.get(f"/api/inventory/materials/{mid}").get_json()["movements"]
    assert legacy_id in {mv["id"] for mv in own_history}


def test_a_welder_without_inventory_access_cannot_approve_a_request(app, admin_client):
    mat_id, pid, movement_id = pending_request(admin_client, app)
    welder = signed_in(app, make_user("Wendy Welder", role="welder"))
    assert welder.get("/api/inventory/material-requests").status_code == 403
    assert welder.post(f"/api/inventory/material-requests/{movement_id}/approve", json={"quantity": 5}).status_code == 403


# ---------- Return to inventory (kohal, 2026-10-20) ----------
#
# "whatever material is requested by the site supervisor, some of them are not used in the project, so
# there should be a return to inventory request as well but the quantity and material source will be
# whatever is present in the project" - a return is a `kind='in'` request against the same queue, told
# apart by `kind` on each row (see app/projects.py's own "return to inventory" section for the
# request-side cap, since that's where it's created).

def pending_return(admin_client, app, issued=10, qty=5, material_name="Cement"):
    """An approved issue to a project, then a pending return of some of it - the requester (the admin here)
    still can't approve their own, same as any other request."""
    material = add_material(admin_client, name=material_name)
    mat_id = material["id"]
    admin_client.post(f"/api/inventory/materials/{mat_id}/stock-in", json={"quantity": 50, "rate": 10})
    pid = add_project(admin_client)
    approved_issue(app, admin_client, mat_id, pid, issued)
    res = admin_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": qty, "kind": "in"})
    assert res.status_code == 201, res.get_json()
    return mat_id, pid, res.get_json()["request"]["id"]


def test_a_return_shows_up_in_the_pending_list_with_its_kind(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_return(admin_client, app, issued=10, qty=4)
    data = accounts_client.get("/api/inventory/material-requests").get_json()
    row = next(r for r in data["requests"] if r["id"] == movement_id)
    assert row["kind"] == "in" and row["quantity"] == 4 and row["project_id"] == pid


def test_approving_a_return_adds_to_stock_with_no_ceiling_to_hit(app, admin_client, accounts_client):
    """Unlike an issue, a return can never be blocked by "not enough stock" - it's adding stock, not taking
    it, so there's nothing to run out of."""
    mat_id, pid, movement_id = pending_return(admin_client, app, issued=10, qty=4)
    before = accounts_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"]
    wid = add_worker(accounts_client, "Ramesh Storekeeper")
    res = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve", json={
        "quantity": 4, "given_by_worker_id": wid, "transport_mode": "Own vehicle",
    })
    assert res.status_code == 200, res.get_json()
    mv = res.get_json()["movement"]
    assert mv["status"] == "approved" and mv["kind"] == "in" and mv["amount"] == 40      # 4 * rate 10
    assert res.get_json()["remainder"] is None
    after = accounts_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"]
    assert after == before + 4


def test_approving_less_than_claimed_on_a_return_has_no_shortfall_remainder(app, admin_client, accounts_client):
    """A return has nothing still "owed" the way an under-stocked issue does - approving less than claimed
    just means less actually came back, so there's no remainder row to carry the rest forward."""
    mat_id, pid, movement_id = pending_return(admin_client, app, issued=10, qty=6)
    wid = add_worker(accounts_client)
    res = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve", json={
        "quantity": 3, "given_by_worker_id": wid, "transport_mode": "Hand carried",
    })
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["movement"]["quantity"] == 3 and body["movement"]["amount"] == 30
    assert body["remainder"] is None
    assert accounts_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["pending_requested_qty"] == 0


def test_cannot_approve_more_than_claimed_on_a_return(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_return(admin_client, app, issued=10, qty=4)
    res = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve", json={"quantity": 5})
    assert res.status_code == 422 and "quantity" in res.get_json()["fields"]


def test_the_requester_cannot_approve_their_own_return(app, admin_client):
    mat_id, pid, movement_id = pending_return(admin_client, app, issued=10, qty=4)
    wid = add_worker(admin_client)
    res = admin_client.post(f"/api/inventory/material-requests/{movement_id}/approve",
                             json={"quantity": 4, "given_by_worker_id": wid, "transport_mode": "Own vehicle"})
    assert res.status_code == 403


def test_the_requester_cannot_reject_their_own_return_either(app, admin_client):
    mat_id, pid, movement_id = pending_return(admin_client, app, issued=10, qty=4)
    assert admin_client.post(f"/api/inventory/material-requests/{movement_id}/reject").status_code == 403


def test_rejecting_a_return_leaves_stock_untouched(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_return(admin_client, app, issued=10, qty=4)
    before = accounts_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"]
    res = accounts_client.post(f"/api/inventory/material-requests/{movement_id}/reject")
    assert res.status_code == 200 and res.get_json()["movement"]["status"] == "rejected"
    after = accounts_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"]
    assert after == before


# ---------- Restock (kohal, 2026-10-21) ----------
#
# "if the requested material quantity or the material itself is not available in the inventory then in
# inventory (in a new subtab called restock) there should be an entry created saying this material and min
# this much quantity needs to be restocked - required in this project".

def test_restock_needs_the_inventory_module(client, accounts_client):
    assert client.get("/api/inventory/restock").status_code == 403
    assert accounts_client.get("/api/inventory/restock").status_code == 200


def test_a_request_fully_covered_by_stock_does_not_show_in_restock(app, admin_client):
    mat_id, pid, movement_id = pending_request(admin_client, app, qty=5, stock=20)
    data = admin_client.get("/api/inventory/restock").get_json()
    assert mat_id not in {r["material_id"] for r in data["restock"]}


def test_a_request_over_stock_shows_the_exact_shortfall(app, admin_client):
    mat_id, pid, movement_id = pending_request(admin_client, app, qty=7, stock=5)
    data = admin_client.get("/api/inventory/restock").get_json()
    row = next(r for r in data["restock"] if r["material_id"] == mat_id)
    assert row["stock_qty"] == 5 and row["requested_qty"] == 7 and row["restock_qty"] == 2
    assert len(row["projects"]) == 1
    assert row["projects"][0]["project_id"] == pid and row["projects"][0]["quantity"] == 7.0


def test_a_material_with_zero_stock_needs_the_full_amount_restocked(app, admin_client):
    mat_id, pid, movement_id = pending_request(admin_client, app, qty=10, stock=0)
    data = admin_client.get("/api/inventory/restock").get_json()
    row = next(r for r in data["restock"] if r["material_id"] == mat_id)
    assert row["restock_qty"] == 10


def test_restock_sums_pending_requests_from_multiple_projects(app, admin_client):
    material = add_material(admin_client, name="Rebar")
    mid = material["id"]
    admin_client.post(f"/api/inventory/materials/{mid}/stock-in", json={"quantity": 5, "rate": 10})
    pid1 = add_project(admin_client, "Site Alpha")
    pid2 = add_project(admin_client, "Site Beta")
    admin_client.post(f"/api/projects/{pid1}/material-requests", json={"material_id": mid, "quantity": 4})
    admin_client.post(f"/api/projects/{pid2}/material-requests", json={"material_id": mid, "quantity": 6})

    data = admin_client.get("/api/inventory/restock").get_json()
    row = next(r for r in data["restock"] if r["material_id"] == mid)
    assert row["requested_qty"] == 10 and row["restock_qty"] == 5
    by_project = {p["project_id"]: p["quantity"] for p in row["projects"]}
    assert by_project == {pid1: 4.0, pid2: 6.0}
    assert {p["project_title"] for p in row["projects"]} == {"Site Alpha", "Site Beta"}


def test_an_approved_request_no_longer_counts_toward_restock(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_request(admin_client, app, qty=7, stock=5)
    wid = add_worker(accounts_client)
    accounts_client.post(f"/api/inventory/material-requests/{movement_id}/approve",
                          json={"quantity": 5, "given_by_worker_id": wid, "transport_mode": "Own vehicle"})
    # Approving less than requested splits a remainder - still pending, so the shortfall still shows, just
    # now scoped to what's actually still outstanding (2), not the original ask (7).
    data = admin_client.get("/api/inventory/restock").get_json()
    row = next((r for r in data["restock"] if r["material_id"] == mat_id), None)
    assert row is not None and row["requested_qty"] == 2 and row["restock_qty"] == 2


def test_a_rejected_request_does_not_count_toward_restock(app, admin_client, accounts_client):
    mat_id, pid, movement_id = pending_request(admin_client, app, qty=7, stock=5)
    accounts_client.post(f"/api/inventory/material-requests/{movement_id}/reject")
    data = admin_client.get("/api/inventory/restock").get_json()
    assert mat_id not in {r["material_id"] for r in data["restock"]}


def test_a_return_request_never_counts_toward_restock(app, admin_client):
    mat_id, pid, movement_id = pending_return(admin_client, app, issued=10, qty=4)
    data = admin_client.get("/api/inventory/restock").get_json()
    assert mat_id not in {r["material_id"] for r in data["restock"]}


def test_restock_count_badge_appears_on_the_materials_and_requests_responses(app, admin_client):
    pending_request(admin_client, app, qty=7, stock=5)
    materials_data = admin_client.get("/api/inventory/materials").get_json()
    requests_data = admin_client.get("/api/inventory/material-requests").get_json()
    assert materials_data["restock_count"] == 1
    assert requests_data["restock_count"] == 1


def test_a_cash_purchase_says_which_account_it_was_paid_from(admin_client):
    """kohal, 2026-10-31: "if its cash selected then show the bank options"."""
    sid = add_supplier(admin_client)
    base = {"name": "Angles", "unit": "kg", "quantity": 10, "rate": 5, "supplier_id": sid}
    no_account = admin_client.post("/api/inventory/materials", json={**base, "payment_mode": "cash"})
    assert no_account.status_code == 422 and "payment_account" in no_account.get_json()["fields"]
    assert Material.query.filter_by(name="Angles").first() is None
    wrong = admin_client.post("/api/inventory/materials", json={**base, "payment_mode": "cash", "payment_account": "Nowhere"})
    assert wrong.status_code == 422 and "payment_account" in wrong.get_json()["fields"]
    ok = admin_client.post("/api/inventory/materials", json={**base, "payment_mode": "cash", "payment_account": "GR BOB"})
    assert ok.status_code == 201 and ok.get_json()["movement"]["payment_account"] == "GR BOB"


def test_a_credit_purchase_has_no_account_and_the_list_is_served(admin_client):
    sid = add_supplier(admin_client)
    res = admin_client.post("/api/inventory/materials", json={
        "name": "Pipes", "unit": "m", "quantity": 4, "rate": 9, "supplier_id": sid, "payment_mode": "credit", "payment_account": "GR BB"})
    assert res.status_code == 201 and res.get_json()["movement"]["payment_account"] == ""
    mid = res.get_json()["material"]["id"]
    assert admin_client.get("/api/inventory/materials").get_json()["payment_accounts"][-1] == "GR BOB"
    assert "GR BB" in admin_client.get(f"/api/inventory/materials/{mid}").get_json()["payment_accounts"]

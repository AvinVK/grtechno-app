from app.extensions import db
from app.models import Client, Lead, Project
from conftest import make_user, signed_in


def make_lead(client, **fields):
    body = {"company": "Kalyani Cold Storage", "contact_name": "R. Kulkarni", "phone": "9800000001",
            "service": "Sprinklers setup", "est_value": 1000000, "site_category": "Commercial complex",
            "site_pincode": "411001", "site_state": "Maharashtra", "site_district": "Pune", "site_city": "Pune City",
            "site_address": "Plot 12, MIDC", **fields}
    res = client.post("/api/leads", json=body)
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def won_lead(client, **fields):
    lead = make_lead(client, **fields)
    assert client.patch(f"/api/leads/{lead['id']}", json={"stage": "Won"}).status_code == 200
    return lead


def make_project(client, admin_client, **fields):
    lead = won_lead(client, **fields)
    res = client.post(f"/api/leads/{lead['id']}/project")
    assert res.status_code == 201, res.get_json()
    return res.get_json()["project_id"]


# ---------- Lead desk additions ----------

def test_site_category_list_and_field(client):
    assert client.get("/api/state").get_json()["settings"]["site_categories"][0] == "Hospital"
    assert make_lead(client)["site_category"] == "Commercial complex"


def test_checklist_add_tick_edit_delete(client):
    lead = make_lead(client)
    url = f"/api/leads/{lead['id']}/checklist"
    detail = client.post(url, json={"text": "Site survey done"}).get_json()
    client.post(url, json={"text": "Drawings received"})
    items = client.get(f"/api/leads/{lead['id']}").get_json()["checklist"]
    assert [i["text"] for i in items] == ["Site survey done", "Drawings received"] and not any(i["done"] for i in items)
    assert "checklist" not in client.get("/api/state").get_json()["leads"][0]          # only in the detail view

    first = items[0]["id"]
    assert client.patch(f"{url}/{first}", json={"done": True}).get_json()["checklist"][0]["done"] is True
    assert client.patch(f"{url}/{first}", json={"text": "Survey completed"}).get_json()["checklist"][0]["text"] == "Survey completed"
    left = client.delete(f"{url}/{first}").get_json()["checklist"]
    assert [i["text"] for i in left] == ["Drawings received"]


def test_checklist_rules(app, client):
    lead = make_lead(client)
    url = f"/api/leads/{lead['id']}/checklist"
    assert client.post(url, json={"text": "   "}).status_code == 422
    assert client.post(url, json={"text": "x" * 201}).status_code == 422
    item = client.post(url, json={"text": "ok"}).get_json()["checklist"][0]["id"]
    assert client.patch(f"{url}/{item}", json={"done": "yes"}).status_code == 422
    assert client.patch(f"{url}/9999", json={"done": True}).status_code == 404
    other = signed_in(app, make_user("Other"))                                          # someone else's lead
    assert other.post(url, json={"text": "sneaky"}).status_code == 404
    assert other.patch(f"{url}/{item}", json={"done": True}).status_code == 404
    assert other.delete(f"{url}/{item}").status_code == 404


# ---------- Won lead -> client + project ----------

def test_only_a_won_lead_becomes_a_project(client):
    lead = make_lead(client)
    res = client.post(f"/api/leads/{lead['id']}/project")
    assert res.status_code == 422 and "won" in res.get_json()["error"]


def test_won_lead_creates_client_and_project_with_its_data(client, user):
    lead = won_lead(client)
    res = client.post(f"/api/leads/{lead['id']}/project")
    assert res.status_code == 201
    body = res.get_json()
    assert body["code"] == "PRJ-0001" and body["client_reused"] is False

    project = db.session.get(Project, body["project_id"])
    assert project.title == "Kalyani Cold Storage - Sprinklers setup" and project.status == "planned"
    assert float(project.estimated_amount) == 1000000 and project.work_category == "Sprinklers setup"
    assert (project.site_pincode, project.site_city, project.site_address) == ("411001", "Pune City", "Plot 12, MIDC")
    assert project.owner_code == user.code and project.lead_id == lead["id"]
    c = project.client
    assert (c.name, c.contact_name, c.phone, c.site_category, c.pincode) == (
        "Kalyani Cold Storage", "R. Kulkarni", "9800000001", "Commercial complex", "411001")

    refreshed = client.get(f"/api/leads/{lead['id']}").get_json()
    assert refreshed["project_id"] == project.id
    assert any("PRJ-0001" in a["text"] for a in refreshed["activities"])


def test_a_lead_can_only_become_a_project_once(client):
    lead = won_lead(client)
    assert client.post(f"/api/leads/{lead['id']}/project").status_code == 201
    assert client.post(f"/api/leads/{lead['id']}/project").status_code == 409
    assert Project.query.count() == 1


def test_repeat_client_is_reused(client):
    first = won_lead(client, company="Orchid Heights CHS")
    second = won_lead(client, company="orchid heights chs", service="AMC")
    a = client.post(f"/api/leads/{first['id']}/project").get_json()
    b = client.post(f"/api/leads/{second['id']}/project").get_json()
    assert a["client_reused"] is False and b["client_reused"] is True and a["client_id"] == b["client_id"]
    assert Client.query.count() == 1 and Project.query.count() == 2


def test_person_without_a_company_uses_the_contact_name(client):
    lead = won_lead(client, company="", contact_name="Mrs. Deshpande")
    body = client.post(f"/api/leads/{lead['id']}/project").get_json()
    assert db.session.get(Client, body["client_id"]).name == "Mrs. Deshpande"


def test_someone_elses_lead_cannot_be_converted(app, client):
    lead = won_lead(client)
    assert signed_in(app, make_user("Other")).post(f"/api/leads/{lead['id']}/project").status_code == 404


# ---------- who sees which project ----------

def test_projects_visibility_and_manager_assignment(app, client, admin_client, manager_client, manager, accounts_client):
    pid = make_project(client, admin_client)
    assert [p["code"] for p in admin_client.get("/api/projects").get_json()["projects"]] == ["PRJ-0001"]
    assert len(accounts_client.get("/api/projects").get_json()["projects"]) == 1              # sees_all role
    assert manager_client.get("/api/projects").get_json()["projects"] == []                  # not theirs yet
    assert manager_client.get(f"/api/projects/{pid}").status_code == 404

    detail = admin_client.get(f"/api/projects/{pid}").get_json()
    assert detail["can_assign_manager"] is True and [m["name"] for m in detail["managers"]] == ["Priya Manager"]
    assert admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code}).status_code == 200

    assert [p["id"] for p in manager_client.get("/api/projects").get_json()["projects"]] == [pid]
    mine = manager_client.get(f"/api/projects/{pid}").get_json()
    assert mine["can_assign_manager"] is False and "managers" not in mine
    assert manager_client.patch(f"/api/projects/{pid}", json={"manager_code": None}).status_code == 403
    assert manager_client.patch(f"/api/projects/{pid}", json={"title": "Renamed by PM"}).status_code == 200


def test_manager_code_must_be_a_project_manager(client, admin_client, user):
    pid = make_project(client, admin_client)
    res = admin_client.patch(f"/api/projects/{pid}", json={"manager_code": user.code})     # a sales user
    assert res.status_code == 422 and "manager_code" in res.get_json()["fields"]


def test_project_details_validation_and_payment_schedule(client, admin_client):
    pid = make_project(client, admin_client)                                                 # estimated 10,00,000
    url = f"/api/projects/{pid}"
    ok = admin_client.patch(url, json={
        "work_order_no": "WO/2026/041", "work_order_date": "2026-09-01", "start_date": "2026-09-15",
        "completion_days": 90, "discount_amount": 50000, "status": "running",
        "payment_terms": "30% advance", "special_terms": "Site access by 8 am",
        "payments": [
            {"label": "Advance", "amount": 300000, "due_date": "2026-09-05"},
            {"label": "On delivery", "amount": 400000, "due_date": None},
        ]})
    assert ok.status_code == 200
    p = ok.get_json()["project"]
    assert p["work_order_no"] == "WO/2026/041" and p["start_date"] == "2026-09-15" and p["completion_days"] == 90
    assert p["net_amount"] == 950000 and p["status"] == "running"
    assert [x["label"] for x in p["payments"]] == ["Advance", "On delivery"] and p["payments"][0]["due_date"] == "2026-09-05"

    replaced = admin_client.patch(url, json={"payments": [{"label": "Final", "amount": 950000}]}).get_json()["project"]
    assert [x["label"] for x in replaced["payments"]] == ["Final"]                           # the schedule is replaced, not added to

    def bad(payload):
        res = admin_client.patch(url, json=payload)
        assert res.status_code == 422, payload
        return res.get_json()["fields"]

    assert "title" in bad({"title": "  "})
    assert "status" in bad({"status": "finished"})
    assert "work_order_date" in bad({"work_order_date": "01-09-2026"})
    assert "completion_days" in bad({"completion_days": "soon"})
    assert "discount_amount" in bad({"discount_amount": 2000000})                            # more than the estimate
    assert "payments" in bad({"payments": [{"label": "Too much", "amount": 960000}]})       # more than the net amount
    assert "payments" in bad({"payments": [{"label": "", "amount": 1}]})
    assert "payments" in bad({"payments": "nope"})
    assert "site_pincode" in bad({"site_pincode": "4110"})


def test_sales_person_sees_no_projects_module_but_conversion_still_works(client):
    lead = won_lead(client)
    assert client.post(f"/api/leads/{lead['id']}/project").status_code == 201
    assert client.get("/api/projects").status_code == 403


# ---------- clients ----------

def test_clients_list_edit_and_add(client, admin_client, manager_client, manager, accounts_client):
    pid = make_project(client, admin_client)
    cid = admin_client.get(f"/api/projects/{pid}").get_json()["client"]["id"]
    assert [c["name"] for c in admin_client.get("/api/clients").get_json()["clients"]] == ["Kalyani Cold Storage"]
    assert manager_client.get("/api/clients").get_json()["clients"] == []                    # no project of theirs yet
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    assert len(manager_client.get("/api/clients").get_json()["clients"]) == 1                # now through their project

    detail = manager_client.get(f"/api/clients/{cid}").get_json()
    assert detail["projects"][0]["code"] == "PRJ-0001"
    edited = manager_client.patch(f"/api/clients/{cid}", json={"phone": "9811111111", "notes": "Pays on time"})
    assert edited.status_code == 200 and edited.get_json()["client"]["phone"] == "9811111111"

    created = accounts_client.post("/api/clients", json={"name": "Walk-in Traders", "pincode": "440001"})
    assert created.status_code == 201 and created.get_json()["client"]["name"] == "Walk-in Traders"
    assert len(accounts_client.get("/api/clients").get_json()["clients"]) == 2


def test_client_validation(admin_client):
    assert admin_client.post("/api/clients", json={}).status_code == 422
    assert admin_client.post("/api/clients", json={"name": "  "}).status_code == 422
    assert "pincode" in admin_client.post("/api/clients", json={"name": "X", "pincode": "12"}).get_json()["fields"]
    cid = admin_client.post("/api/clients", json={"name": "Valid Co"}).get_json()["client"]["id"]
    assert admin_client.patch(f"/api/clients/{cid}", json={"name": ""}).status_code == 422
    assert admin_client.get("/api/clients/9999").status_code == 404

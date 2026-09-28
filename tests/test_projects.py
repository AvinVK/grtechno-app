from datetime import date

from app.extensions import db
from app.models import Attendance, Client, Lead, Project, ProjectPayment, Service, User
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
    """Winning a lead now creates its client/project automatically - returns the lead as it stood right
    before winning it (fields like company/service), same as before, for callers that only need those."""
    lead = make_lead(client, **fields)
    res = client.patch(f"/api/leads/{lead['id']}", json={"stage": "Won"})
    assert res.status_code == 200, res.get_json()
    return lead


def make_project(client, admin_client, **fields):
    lead = won_lead(client, **fields)
    detail = client.get(f"/api/leads/{lead['id']}").get_json()
    return detail["project_id"]


# ---------- Leads additions ----------

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
    detail = client.get(f"/api/leads/{lead['id']}").get_json()
    project = db.session.get(Project, detail["project_id"])
    assert project.code == "PRJ-0001"
    assert project.title == "Kalyani Cold Storage - Sprinklers setup" and project.status == "planned"
    assert float(project.estimated_amount) == 1000000 and project.work_category == "Sprinklers setup"
    assert (project.site_pincode, project.site_city, project.site_address) == ("411001", "Pune City", "Plot 12, MIDC")
    assert project.owner_code == user.code and project.lead_id == lead["id"]
    c = project.client
    assert (c.name, c.contact_name, c.phone, c.site_category, c.pincode) == (
        "Kalyani Cold Storage", "R. Kulkarni", "9800000001", "Commercial complex", "411001")
    assert any("PRJ-0001" in a["text"] for a in detail["activities"])

    # The manual endpoint is still there as a fallback, but a lead only ever becomes a project once.
    assert client.post(f"/api/leads/{lead['id']}/project").status_code == 409
    assert Project.query.count() == 1


def test_repeat_client_is_reused(client):
    first = won_lead(client, company="Orchid Heights CHS")
    second = won_lead(client, company="orchid heights chs", service="AMC")
    a = client.get(f"/api/leads/{first['id']}").get_json()
    b = client.get(f"/api/leads/{second['id']}").get_json()
    a_client = db.session.get(Project, a["project_id"]).client_id
    b_client = db.session.get(Project, b["project_id"]).client_id
    assert a_client == b_client
    assert Client.query.count() == 1 and Project.query.count() == 2


def test_person_without_a_company_uses_the_contact_name(client):
    lead = won_lead(client, company="", contact_name="Mrs. Deshpande")
    detail = client.get(f"/api/leads/{lead['id']}").get_json()
    project = db.session.get(Project, detail["project_id"])
    assert project.client.name == "Mrs. Deshpande"


def test_someone_elses_lead_cannot_be_converted(app, client):
    lead = won_lead(client)
    assert signed_in(app, make_user("Other")).post(f"/api/leads/{lead['id']}/project").status_code == 404


def test_the_project_list_carries_the_site_location(client, admin_client):
    make_project(client, admin_client)
    row = admin_client.get("/api/projects").get_json()["projects"][0]
    assert row["site_district"] == "Pune" and row["site_city"] == "Pune City"


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
    assert client.get(f"/api/leads/{lead['id']}").get_json()["project_id"] is not None
    assert client.get("/api/projects").status_code == 403


# ---------- clients ----------

def test_clients_list_and_edit(client, admin_client, manager_client, manager, accounts_client):
    pid = make_project(client, admin_client)
    cid = admin_client.get(f"/api/projects/{pid}").get_json()["client"]["id"]
    assert [c["name"] for c in admin_client.get("/api/clients").get_json()["clients"]] == ["Kalyani Cold Storage"]
    assert manager_client.get("/api/clients").get_json()["clients"] == []                    # no project of theirs yet
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    assert len(manager_client.get("/api/clients").get_json()["clients"]) == 1                # now through their project

    detail = manager_client.get(f"/api/clients/{cid}").get_json()
    assert detail["projects"][0]["code"] == "PRJ-0001"
    assert detail["client"]["created_at"].endswith("Z")                                      # "Client for ..." on the summary
    edited = manager_client.patch(f"/api/clients/{cid}", json={"phone": "9811111111", "notes": "Pays on time"})
    assert edited.status_code == 200 and edited.get_json()["client"]["phone"] == "9811111111"


def test_clients_are_never_created_by_hand(admin_client):
    # No add-client endpoint any more - a client only ever comes from winning a lead (or the direct
    # "already running" project path below, for work that predates this pipeline).
    assert admin_client.post("/api/clients", json={"name": "Walk-in Traders"}).status_code == 405


def test_client_validation(admin_client):
    cid = admin_client.post("/api/projects", json={"new_client_name": "Valid Co"}).get_json()["project"]["client_id"]
    assert admin_client.patch(f"/api/clients/{cid}", json={"name": ""}).status_code == 422
    assert "pincode" in admin_client.patch(f"/api/clients/{cid}", json={"name": "Valid Co", "pincode": "12"}).get_json()["fields"]
    assert admin_client.get("/api/clients/9999").status_code == 404


# ---------- adding a project directly (work that is already running) ----------

def test_admin_adds_a_project_with_a_new_client(admin_client, admin):
    res = admin_client.post("/api/projects", json={"new_client_name": "Sunrise Hospital", "work_category": "AMC"})
    assert res.status_code == 201
    project = res.get_json()["project"]
    assert project["code"] == "PRJ-0001" and project["client_name"] == "Sunrise Hospital"
    assert project["status"] == "running" and project["title"] == "Sunrise Hospital - AMC"      # sensible defaults
    assert project["manager_code"] is None and project["lead_id"] is None
    client = Client.query.one()
    assert client.name == "Sunrise Hospital" and client.owner_code == admin.code


def test_add_project_for_an_existing_client_and_custom_details(admin_client):
    cid = admin_client.post("/api/projects", json={"new_client_name": "Orchid Heights CHS"}).get_json()["project"]["client_id"]
    res = admin_client.post("/api/projects", json={"client_id": cid, "title": "Fire alarm upgrade", "status": "on_hold"})
    assert res.status_code == 201
    assert res.get_json()["project"]["title"] == "Fire alarm upgrade" and res.get_json()["project"]["status"] == "on_hold"
    assert Client.query.count() == 1                                                          # the client was reused, not duplicated
    db.session.add(Service(name="AMC", sort_order=1))
    db.session.commit()
    listing = admin_client.get("/api/projects").get_json()
    assert [c["name"] for c in listing["clients"]] == ["Orchid Heights CHS"] and "AMC" in listing["services"]


def test_a_new_client_name_that_already_exists_is_reused(admin_client):
    admin_client.post("/api/projects", json={"new_client_name": "Greenfield Warehousing"})
    admin_client.post("/api/projects", json={"new_client_name": "greenfield warehousing"})
    assert Client.query.count() == 1 and Project.query.count() == 2


def test_add_project_validation(admin_client):
    def bad(payload):
        res = admin_client.post("/api/projects", json=payload)
        assert res.status_code == 422, payload
        return res.get_json()["fields"]

    assert "client_id" in bad({})                                                             # no client at all
    assert "client_id" in bad({"new_client_name": "   "})
    assert "client_id" in bad({"client_id": 9999})
    assert "client_id" in bad({"client_id": "abc"})
    assert "status" in bad({"new_client_name": "X", "status": "finished"})
    assert "title" in bad({"new_client_name": "X", "title": "t" * 161})
    assert Project.query.count() == 0


def test_project_manager_adds_and_runs_their_own_project(manager_client, manager, admin_client):
    res = manager_client.post("/api/projects", json={"new_client_name": "Pinnacle IT Park", "work_category": "Fire alarms"})
    assert res.status_code == 201
    assert res.get_json()["project"]["manager_name"] == "Priya Manager" and res.get_json()["project"]["manager_code"] == manager.code
    assert len(manager_client.get("/api/projects").get_json()["projects"]) == 1                # it is theirs, so they see it

    # a client that belongs to someone else's project is not on their list
    other = admin_client.post("/api/projects", json={"new_client_name": "Someone Else Ltd"}).get_json()["project"]["client_id"]
    assert manager_client.post("/api/projects", json={"client_id": other}).status_code == 422
    assert [c["name"] for c in manager_client.get("/api/projects").get_json()["clients"]] == ["Pinnacle IT Park"]


def test_accounts_can_add_a_project_and_sales_cannot(accounts_client, client):
    res = accounts_client.post("/api/projects", json={"new_client_name": "Walk-in Traders"})
    assert res.status_code == 201 and res.get_json()["project"]["manager_code"] is None        # assigned later by admin/accounts
    assert client.post("/api/projects", json={"new_client_name": "Nope"}).status_code == 403


# ---------- project dashboard ----------

def test_dashboard_shows_start_brought_by_and_who_worked_on_it(app, client, admin_client, admin):
    from datetime import date, timedelta
    from app.models import Attendance, Worker, WorkerAttendance
    with app.app_context():
        staff = Worker(name="Priya Frontdesk", category="staff")
        db.session.add(staff)
        db.session.commit()
        staff_id = staff.id
    pid = make_project(client, admin_client, enquired_by_id=staff_id)
    with app.app_context():
        welder = Worker(name="Sunny Welder", category="manpower")
        db.session.add(welder)
        db.session.flush()
        today = date.today()
        for back in (0, 1, 2):
            db.session.add(WorkerAttendance(worker=welder, work_date=today - timedelta(days=back), project_id=pid))
        db.session.add(WorkerAttendance(worker=welder, work_date=today - timedelta(days=3), project_id=pid, status="absent"))
        db.session.add(Attendance(user_code=admin.code, work_date=today, project_id=pid, check_in_at=db.func.now()))
        db.session.commit()

    dash = admin_client.get(f"/api/projects/{pid}").get_json()["dashboard"]
    from app.timeutil import today_local
    assert dash["started"] == today_local().isoformat() and dash["start_date_set"] is False    # the local day it was added
    assert dash["brought_by"] == {"name": "Priya Frontdesk", "how": "Took the enquiry"}
    assert [(m["name"], m["kind"], m["days"]) for m in dash["team"]] == [("Sunny Welder", "Manpower", 3), (admin.name, "App user", 1)]
    assert dash["can_close"] is True and dash["completed_at"] is None

    admin_client.patch(f"/api/projects/{pid}", json={"title": "Sprinklers", "start_date": "2026-01-05"})
    dash = admin_client.get(f"/api/projects/{pid}").get_json()["dashboard"]
    assert dash["started"] == "2026-01-05" and dash["start_date_set"] is True


def test_brought_by_falls_back_to_whoever_entered_the_lead(client, admin_client, user):
    pid = make_project(client, admin_client)
    assert admin_client.get(f"/api/projects/{pid}").get_json()["dashboard"]["brought_by"] == {"name": user.name, "how": "Entered the lead"}
    cid = admin_client.get(f"/api/projects/{pid}").get_json()["client"]["id"]
    assert admin_client.get(f"/api/clients/{cid}").get_json()["brought_by"]["name"] == user.name


def test_only_the_admin_can_close_a_project(client, admin_client, accounts_client, manager_client, manager):
    pid = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid}", json={"title": "Sprinklers", "manager_code": manager.code})
    assert accounts_client.get(f"/api/projects/{pid}").get_json()["dashboard"]["can_close"] is False
    for who in (accounts_client, manager_client):
        assert who.post(f"/api/projects/{pid}/close").status_code == 403

    closed = admin_client.post(f"/api/projects/{pid}/close")
    assert closed.status_code == 200
    body = closed.get_json()
    assert body["project"]["status"] == "completed" and body["dashboard"]["completed_at"].endswith("Z")
    assert admin_client.post(f"/api/projects/{pid}/close").status_code == 409


def test_completed_at_follows_the_status_when_edited(client, admin_client):
    pid = make_project(client, admin_client)
    url = f"/api/projects/{pid}"
    assert admin_client.patch(url, json={"title": "T", "status": "completed"}).get_json()["dashboard"]["completed_at"]
    assert admin_client.patch(url, json={"title": "T", "status": "running"}).get_json()["dashboard"]["completed_at"] is None


def test_only_the_admin_can_delete_a_project(client, admin_client, accounts_client, manager_client, manager, app):
    """TEMPORARY - the delete is only there for the backfill."""
    pid = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid}", json={"title": "Sprinklers", "manager_code": manager.code,
                                                     "payments": [{"label": "Advance", "amount": 100}]})
    with app.app_context():
        admin = User.query.filter_by(is_admin=True).first()
        db.session.add(Attendance(user_code=admin.code, work_date=date.today(), project_id=pid, check_in_at=db.func.now()))
        db.session.commit()
    assert admin_client.get(f"/api/projects/{pid}").get_json()["dashboard"]["can_delete"] is True
    assert accounts_client.get(f"/api/projects/{pid}").get_json()["dashboard"]["can_delete"] is False
    for who in (client, accounts_client, manager_client):
        assert who.delete(f"/api/projects/{pid}").status_code == 403

    assert admin_client.delete(f"/api/projects/{pid}").status_code == 204
    assert admin_client.get(f"/api/projects/{pid}").status_code == 404
    assert admin_client.delete(f"/api/projects/{pid}").status_code == 404
    with app.app_context():
        assert ProjectPayment.query.count() == 0
        assert Attendance.query.one().project_id is None       # the attendance stays, just without a project

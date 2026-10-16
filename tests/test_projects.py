from datetime import date

from app.extensions import db
from app.models import Attendance, Client, Lead, Project, ProjectPayment, RoleModule, Service, User, utcnow
from conftest import make_user, signed_in, win_lead


def make_lead(client, **fields):
    body = {"company": "Kalyani Cold Storage", "contact_name": "R. Kulkarni", "phone": "9800000001",
            "service": "Sprinklers setup", "est_value": 1000000, **fields}
    res = client.post("/api/leads", json=body)
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def won_lead(client, admin_client, **fields):
    """Create a lead and drive it all the way to Won (see conftest.win_lead) - returns the lead as it
    stood right after winning."""
    lead = make_lead(client, **fields)
    return win_lead(client, admin_client, lead["id"])


def make_project(client, admin_client, **fields):
    lead = won_lead(client, admin_client, **fields)
    return lead["project_id"]


# ---------- Leads additions ----------

def test_site_category_list_and_field(client):
    assert client.get("/api/state").get_json()["settings"]["site_categories"][0] == "Hospital"
    lead = make_lead(client)
    res = client.put(f"/api/leads/{lead['id']}/survey", json={"site_category": "Commercial complex"})
    assert res.get_json()["survey"]["site_category"] == "Commercial complex"


# ---------- Won lead -> client + project ----------

def test_only_a_won_lead_becomes_a_project(client):
    lead = make_lead(client)
    res = client.post(f"/api/leads/{lead['id']}/project")
    assert res.status_code == 422 and "won" in res.get_json()["error"]


def test_won_lead_creates_client_and_project_with_its_data(client, admin_client, user):
    lead = won_lead(client, admin_client)
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


def test_project_title_leads_with_the_site_name_when_the_survey_has_one(client, admin_client):
    # A client can go on to have more than one project - the site name is what tells them apart anywhere
    # a lead or project is listed, so it leads the title instead of the services once the survey has one.
    # Driven by hand, not advance_to_negotiation/win_lead - either would PUT its own survey without a site
    # name, wiping this one back out (upsert_survey replaces every field each call).
    lead = make_lead(client)
    client.put(f"/api/leads/{lead['id']}/survey", json={
        "survey_date": "2026-09-20", "site_name": "Tower B, 4th floor",
        "site_category": "Commercial complex", "site_pincode": "411001", "site_state": "Maharashtra",
        "site_district": "Pune", "site_city": "Pune City", "site_address": "Plot 12, MIDC",
    })
    client.patch(f"/api/leads/{lead['id']}", json={"quote_sent_date": "2026-09-21"})
    client.post(f"/api/leads/{lead['id']}/negotiations", json={
        "date": "2026-09-22", "authorized_person": "Mr. Rao", "estimate": 1000000, "finalized": True,
    })
    client.patch(f"/api/leads/{lead['id']}", json={
        "work_order_no": "WO-1001", "work_order_date": "2026-09-23",
        "advance_amount": 100000, "advance_date": "2026-09-23", "advance_mode": "Bank transfer",
    })
    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Won"})
    detail = client.get(f"/api/leads/{lead['id']}").get_json()
    project = db.session.get(Project, detail["project_id"])
    assert project.title == "Tower B, 4th floor" and project.site_name == "Tower B, 4th floor"


def test_same_company_name_no_longer_auto_reuses_a_client(client, admin_client):
    # Winning no longer guesses by matching names - two enquiries that happen to share a company name
    # get two separate clients unless the admin explicitly maps the second one to the first.
    first = won_lead(client, admin_client, company="Orchid Heights CHS")
    second = won_lead(client, admin_client, company="orchid heights chs", service="AMC")
    a_client = db.session.get(Project, first["project_id"]).client_id
    b_client = db.session.get(Project, second["project_id"]).client_id
    assert a_client != b_client
    assert Client.query.count() == 2 and Project.query.count() == 2


def test_admin_can_explicitly_map_a_won_lead_to_an_existing_client(client, admin_client):
    first = won_lead(client, admin_client, company="Orchid Heights CHS")
    first_client_id = db.session.get(Project, first["project_id"]).client_id

    lead = make_lead(client, company="Orchid Heights CHS - phase 2")
    second = win_lead(client, admin_client, lead["id"], client_id=first_client_id)
    assert db.session.get(Project, second["project_id"]).client_id == first_client_id
    assert Client.query.count() == 1 and Project.query.count() == 2


def test_person_without_a_company_uses_the_contact_name(client, admin_client):
    lead = won_lead(client, admin_client, company="", contact_name="Mrs. Deshpande")
    detail = client.get(f"/api/leads/{lead['id']}").get_json()
    project = db.session.get(Project, detail["project_id"])
    assert project.client.name == "Mrs. Deshpande"


def test_someone_elses_lead_cannot_be_converted(app, client, admin_client):
    lead = won_lead(client, admin_client)
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
    # Project manager sees every project, not just their own (kohal, 2026-10-16) - assigning as its manager
    # only changes who can edit/reassign it, not who can see it.
    assert [p["id"] for p in manager_client.get("/api/projects").get_json()["projects"]] == [pid]
    assert manager_client.get(f"/api/projects/{pid}").status_code == 200

    detail = admin_client.get(f"/api/projects/{pid}").get_json()
    assert detail["can_assign_manager"] is True and [m["name"] for m in detail["managers"]] == ["Priya Manager"]
    assert admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code}).status_code == 200

    assert [p["id"] for p in manager_client.get("/api/projects").get_json()["projects"]] == [pid]
    mine = manager_client.get(f"/api/projects/{pid}").get_json()
    assert mine["can_assign_manager"] is False and "managers" not in mine
    assert manager_client.patch(f"/api/projects/{pid}", json={"manager_code": None}).status_code == 403
    assert manager_client.patch(f"/api/projects/{pid}", json={"title": "Renamed by PM"}).status_code == 200


def test_site_supervisor_only_sees_projects_theyve_checked_into(app, client, admin_client):
    """kohal, 2026-10-16: a site supervisor's project list isn't ownership/management like everyone else's
    fallback - it's whichever projects they've actually checked Attendance into, site by site."""
    visited = make_project(client, admin_client, company="Site They Visited")
    other = make_project(client, admin_client, company="Site They Never Went To")
    supervisor = make_user("Site Sam", role="supervisor")
    db.session.add(Attendance(user_code=supervisor.code, work_date=date.today(),
                               project_id=visited, check_in_at=utcnow()))
    db.session.commit()
    sup_client = signed_in(app, supervisor)
    assert [p["id"] for p in sup_client.get("/api/projects").get_json()["projects"]] == [visited]
    assert sup_client.get(f"/api/projects/{visited}").status_code == 200
    assert sup_client.get(f"/api/projects/{other}").status_code == 404


def test_manager_code_must_be_a_project_manager(client, admin_client, user):
    pid = make_project(client, admin_client)
    res = admin_client.patch(f"/api/projects/{pid}", json={"manager_code": user.code})     # a sales user
    assert res.status_code == 422 and "manager_code" in res.get_json()["fields"]


def test_project_details_validation_and_payment_schedule(client, admin_client):
    pid0 = make_project(client, admin_client)
    renamed = admin_client.patch(f"/api/projects/{pid0}", json={"site_name": "Gate 3, Plant"}).get_json()["project"]
    assert renamed["title"] == "Gate 3, Plant" and renamed["site_name"] == "Gate 3, Plant"
    retitled = admin_client.patch(f"/api/projects/{pid0}", json={"title": "Gate 4"}).get_json()["project"]
    assert retitled["site_name"] == "Gate 4" and retitled["title"] == "Gate 4"

    pid = make_project(client, admin_client)                                                 # estimated 10,00,000
    url = f"/api/projects/{pid}"
    ok = admin_client.patch(url, json={
        "work_order_no": "WO/2026/041", "work_order_date": "2026-09-01", "start_date": "2026-09-15",
        "completion_days": 90, "discount_amount": 50000, "status": "running",
        "payment_terms": "30% advance", "special_terms": "Site access by 8 am",
        "payments": [
            {"label": "Advance", "amount": 300000, "due_date": "2026-09-05",
             "mode": "Bank transfer", "paid_date": "2026-09-04", "comments": "Paid by the client's office"},
            {"label": "On delivery", "amount": 400000, "due_date": None},
        ]})
    assert ok.status_code == 200
    p = ok.get_json()["project"]
    assert p["work_order_no"] == "WO/2026/041" and p["start_date"] == "2026-09-15" and p["completion_days"] == 90
    assert p["net_amount"] == 950000 and p["status"] == "running"
    assert [x["label"] for x in p["payments"]] == ["Advance", "On delivery"] and p["payments"][0]["due_date"] == "2026-09-05"
    assert p["payments"][0]["mode"] == "Bank transfer" and p["payments"][0]["paid_date"] == "2026-09-04"
    assert p["payments"][0]["comments"] == "Paid by the client's office"
    assert p["payments"][1]["mode"] == "" and p["payments"][1]["paid_date"] is None     # left blank: fine, not required

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
    assert "payments" in bad({"payments": [{"label": "Advance", "amount": 1, "mode": "Bitcoin"}]})
    assert "site_pincode" in bad({"site_pincode": "4110"})


def test_sales_person_sees_no_projects_module_but_conversion_still_works(client, admin_client):
    lead = won_lead(client, admin_client)
    assert client.get(f"/api/leads/{lead['id']}").get_json()["project_id"] is not None
    assert client.get("/api/projects").status_code == 403


# ---------- clients ----------

def test_clients_list_and_edit(app, client, admin_client, manager_client, manager, accounts_client):
    # visible_clients()'s "otherwise the ones they created plus the clients of projects they manage" branch
    # needs a role with clients access that isn't sees_all or sub_admin to exercise - project_manager
    # itself has no clients access by default any more (kohal's access matrix, 2026-10-14; see test_roles.py
    # for that), so this test grants it just for itself to keep covering that scoping logic.
    with app.app_context():
        db.session.add(RoleModule(role_key="project_manager", module_key="clients"))
        db.session.commit()
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


def test_clients_can_be_added_directly_and_deleted_when_they_have_no_projects(client, admin_client):
    res = admin_client.post("/api/clients", json={"name": "Walk-in Traders", "site_name": "Shop 4", "site_category": "Commercial"})
    assert res.status_code == 201 and res.get_json()["client"]["site_name"] == "Shop 4"
    assert admin_client.post("/api/clients", json={}).status_code == 422
    cid = res.get_json()["client"]["id"]
    pid = admin_client.post("/api/projects", json={"client_id": cid, "title": "Work"}).get_json()["project"]["id"]
    assert admin_client.delete(f"/api/clients/{cid}").status_code == 422          # has a project
    admin_client.delete(f"/api/projects/{pid}")
    assert client.delete(f"/api/clients/{cid}").status_code == 403                # admin only (no clients access either)
    assert admin_client.delete(f"/api/clients/{cid}").status_code == 204
    assert admin_client.get(f"/api/clients/{cid}").status_code == 404


def test_client_validation(admin_client):
    cid = admin_client.post("/api/projects", json={"new_client_name": "Valid Co"}).get_json()["project"]["client_id"]
    assert admin_client.patch(f"/api/clients/{cid}", json={"name": ""}).status_code == 422
    assert "pincode" in admin_client.patch(f"/api/clients/{cid}", json={"name": "Valid Co", "pincode": "12"}).get_json()["fields"]
    assert admin_client.get("/api/clients/9999").status_code == 404


# ---------- adding a project directly (work that is already running) ----------

def test_admin_adds_a_project_with_a_new_client(admin_client, admin):
    seed_services("AMC")
    res = admin_client.post("/api/projects", json={"new_client_name": "Sunrise Hospital", "services": ["AMC"]})
    assert res.status_code == 201
    project = res.get_json()["project"]
    assert project["code"] == "PRJ-0001" and project["client_name"] == "Sunrise Hospital"
    assert project["status"] == "running" and project["title"] == "Sunrise Hospital - AMC"      # sensible defaults
    assert project["manager_code"] is None and project["lead_id"] is None
    client = Client.query.one()
    assert client.name == "Sunrise Hospital" and client.owner_code == admin.code


def seed_services(*names):
    from app.models import Service
    for i, name in enumerate(names, start=1):
        if not Service.query.filter_by(name=name).first():
            db.session.add(Service(name=name, sort_order=i))
    db.session.commit()


def test_adding_a_project_takes_services_estimate_work_order_and_advance(admin_client):
    seed_services("AMC", "Fire alarms")
    res = admin_client.post("/api/projects", json={
        "new_client_name": "Dhanbad Plaza", "services": ["AMC", "Fire alarms"], "estimated_amount": 250000,
        "work_order_no": "WO-77", "work_order_date": "2026-09-30",
        "advance_amount": 50000, "advance_date": "2026-10-01", "advance_mode": "UPI", "advance_comments": "Office account",
    })
    assert res.status_code == 201, res.get_json()
    project = res.get_json()["project"]
    assert sorted(project["services"]) == ["AMC", "Fire alarms"] and project["title"] == "Dhanbad Plaza - AMC, Fire alarms"
    assert project["estimated_amount"] == 250000 and project["net_amount"] == 250000
    assert project["work_order_no"] == "WO-77" and project["work_order_date"] == "2026-09-30"
    detail = admin_client.get(f"/api/projects/{project['id']}").get_json()
    assert [(p["label"], p["amount"], p["mode"], p["paid_date"], p["comments"]) for p in detail["project"]["payments"]] == [
        ("Advance", 50000, "UPI", "2026-10-01", "Office account")]
    assert detail["project"]["paid_amount"] == 50000


def test_adding_a_project_validates_the_advance_and_services(admin_client):
    bad = admin_client.post("/api/projects", json={
        "new_client_name": "X Co", "services": ["Not a service"], "estimated_amount": 1000,
        "advance_amount": 5000, "advance_mode": "Bitcoin",
    })
    assert bad.status_code == 422
    fields = bad.get_json()["fields"]
    assert "services" in fields and "advance_mode" in fields and "advance_date" in fields and "advance_amount" in fields


def test_fill_amount_sets_negotiated_from_payment_total(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Old Work Ltd"}).get_json()["project"]["id"]
    admin_client.patch(f"/api/projects/{pid}", json={"title": "Old Work", "payments": [
        {"label": "Advance", "amount": 200000}, {"label": "Balance", "amount": 130000}]})
    res = admin_client.patch(f"/api/projects/{pid}", json={"estimated_amount": 330000})
    assert res.status_code == 200 and res.get_json()["project"]["net_amount"] == 330000


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
        staff = Worker(name="Priya Frontdesk", category="staff", role_key="sales_office")
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


def test_recording_the_final_amount_moves_status_to_final_estimate_sent(client, admin_client):
    pid = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid}", json={"title": "Sprinklers", "status": "running"})

    measured = admin_client.patch(f"/api/projects/{pid}", json={"title": "Sprinklers", "final_amount": 150000})
    assert measured.get_json()["project"]["status"] == "final_estimate_sent"

    # Already measured - a later, unrelated edit doesn't touch the status again.
    again = admin_client.patch(f"/api/projects/{pid}", json={"title": "Sprinklers v2", "final_amount": 150000})
    assert again.get_json()["project"]["status"] == "final_estimate_sent"

    # An explicit status in the same request wins over the automatic move.
    pid2 = make_project(client, admin_client, contact_name="Another Co", phone="9800000002")
    explicit = admin_client.patch(f"/api/projects/{pid2}", json={
        "title": "Sprinklers", "status": "on_hold", "final_amount": 90000,
    })
    assert explicit.get_json()["project"]["status"] == "on_hold"


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

    # Closing needs the final measurement on file and fully paid - nothing to measure yet, so this is refused.
    blocked = admin_client.post(f"/api/projects/{pid}/close")
    assert blocked.status_code == 422

    # The won lead's advance (100000) already carried over as a paid step - measuring higher than that
    # leaves a balance, so still refused until it's covered too.
    admin_client.patch(f"/api/projects/{pid}", json={"title": "Sprinklers", "final_amount": 150000})
    still_blocked = admin_client.post(f"/api/projects/{pid}/close")
    assert still_blocked.status_code == 422          # measured, but not fully paid

    admin_client.patch(f"/api/projects/{pid}", json={"title": "Sprinklers", "payments": [
        {"label": "Advance", "amount": 100000, "mode": "Bank transfer", "paid_date": "2026-09-23"},
        {"label": "Final", "amount": 50000, "mode": "Bank transfer", "paid_date": "2026-09-30"},
    ]})
    closed = admin_client.post(f"/api/projects/{pid}/close")
    assert closed.status_code == 200
    body = closed.get_json()
    assert body["project"]["status"] == "completed" and body["dashboard"]["completed_at"].endswith("Z")
    assert admin_client.post(f"/api/projects/{pid}/close").status_code == 409


def test_completed_at_follows_the_status_when_edited(client, admin_client):
    pid = make_project(client, admin_client)
    url = f"/api/projects/{pid}"
    assert admin_client.patch(url, json={"title": "T", "status": "completed"}).status_code == 422
    done = admin_client.patch(url, json={
        "title": "T", "status": "completed", "final_amount": 100000,
        "payments": [{"label": "Final", "amount": 100000, "mode": "Cash", "paid_date": "2026-09-30"}],
    })
    assert done.get_json()["dashboard"]["completed_at"]
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


# ---------- materials used (the project's own expense leg, from Inventory's issue ledger) ----------

def add_material_and_issue(admin_client, project_id, name="Cement", quantity=10, rate=50):
    material = admin_client.post("/api/inventory/materials", json={"name": name, "unit": "bags"}).get_json()["material"]
    admin_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": quantity * 10, "rate": rate})
    res = admin_client.post(f"/api/inventory/materials/{material['id']}/issue",
                             json={"quantity": quantity, "project_id": project_id, "note": "Foundation work"})
    assert res.status_code == 201, res.get_json()
    return material


def test_project_detail_lists_materials_issued_to_it_and_their_total_cost(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Site With Materials"}).get_json()["project"]["id"]
    add_material_and_issue(admin_client, pid, "Cement", quantity=10, rate=50)
    add_material_and_issue(admin_client, pid, "TMT Bars", quantity=5, rate=60)

    detail = admin_client.get(f"/api/projects/{pid}").get_json()
    assert detail["total_material_cost"] == 800                          # 10*50 + 5*60
    materials = detail["materials"]
    assert len(materials) == 2
    assert {m["material_name"] for m in materials} == {"Cement", "TMT Bars"}
    cement = next(m for m in materials if m["material_name"] == "Cement")
    assert cement["quantity"] == 10 and cement["rate"] == 50 and cement["amount"] == 500
    assert cement["note"] == "Foundation work" and cement["material_code"]


def test_project_with_no_materials_issued_has_an_empty_list(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "No Materials Yet"}).get_json()["project"]["id"]
    detail = admin_client.get(f"/api/projects/{pid}").get_json()
    assert detail["materials"] == [] and detail["total_material_cost"] == 0


def test_materials_issued_to_a_different_project_do_not_show_up(admin_client):
    pid1 = admin_client.post("/api/projects", json={"new_client_name": "Project One"}).get_json()["project"]["id"]
    pid2 = admin_client.post("/api/projects", json={"new_client_name": "Project Two"}).get_json()["project"]["id"]
    add_material_and_issue(admin_client, pid1, "Cement", quantity=10, rate=50)
    detail = admin_client.get(f"/api/projects/{pid2}").get_json()
    assert detail["materials"] == []


def test_a_closed_project_can_still_be_deleted(client, admin_client):
    """TEMPORARY - closed/completed projects need the backfill cleanup too."""
    pid = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid}", json={
        "title": "T", "final_amount": 100000,
        "payments": [{"label": "Final", "amount": 100000, "mode": "Cash", "paid_date": "2026-09-30"}],
    })
    admin_client.post(f"/api/projects/{pid}/close")
    dash = admin_client.get(f"/api/projects/{pid}").get_json()["dashboard"]
    assert dash["can_delete"] is True
    assert admin_client.delete(f"/api/projects/{pid}").status_code == 204


# ---------- material requests (kohal, 2026-10-16) ----------
#
# "to assign material to the project, there should be an approval needed from either the site supervisor
# who has currently checked in on that site or project manager"

def stocked_material(admin_client, qty=20, name="Cement"):
    res = admin_client.post("/api/inventory/materials", json={"name": name, "unit": "bags", "quantity": qty, "rate": 10})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["material"]["id"]


def check_in_on(client, project_id):
    res = client.post("/api/attendance/check-in", json={"lat": 21.1458, "lng": 79.0882, "project_id": project_id})
    assert res.status_code == 201, res.get_json()


def test_a_request_from_the_projects_own_manager_is_approved_immediately(app, client, admin_client):
    pid = make_project(client, admin_client)
    manager = make_user("Priya Manager", role="project_manager")
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    mat_id = stocked_material(admin_client)
    pm = signed_in(app, manager)

    res = pm.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})
    assert res.status_code == 201
    body = res.get_json()["request"]
    assert body["status"] == "approved" and body["approved_by_name"] == "Priya Manager"
    assert admin_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"] == 15


def test_a_request_from_a_site_supervisor_checked_in_there_is_approved_immediately(app, client, admin_client):
    pid = make_project(client, admin_client)
    mat_id = stocked_material(admin_client)
    supervisor = make_user("Site Sam", role="supervisor")
    sup_client = signed_in(app, supervisor)
    check_in_on(sup_client, pid)

    res = sup_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})
    assert res.status_code == 201
    assert res.get_json()["request"]["status"] == "approved"
    assert admin_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"] == 15


def test_a_supervisor_not_checked_in_there_cant_even_see_the_project(app, client, admin_client):
    """visible_projects() already hides a project from a site supervisor until they've checked into it, so
    there's nothing to request here in the first place - not a 403, a 404, same as everywhere else that
    scoping applies."""
    pid = make_project(client, admin_client)
    mat_id = stocked_material(admin_client)
    supervisor = make_user("Site Sam", role="supervisor")
    sup_client = signed_in(app, supervisor)
    res = sup_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})
    assert res.status_code == 404


def test_a_request_from_accounts_waits_for_the_project_manager_or_supervisor(app, client, admin_client, accounts_client):
    pid = make_project(client, admin_client)
    manager = make_user("Priya Manager", role="project_manager")
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    mat_id = stocked_material(admin_client)

    res = accounts_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})
    assert res.status_code == 201
    body = res.get_json()["request"]
    assert body["status"] == "pending" and body["approved_by_name"] is None
    assert admin_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"] == 20   # untouched

    movement_id = body["id"]
    pm = signed_in(app, manager)
    # the accountant can't approve their own request - only the manager or a checked-in supervisor can
    assert accounts_client.post(f"/api/projects/{pid}/material-requests/{movement_id}/approve").status_code == 403
    res = pm.post(f"/api/projects/{pid}/material-requests/{movement_id}/approve")
    assert res.status_code == 200
    assert res.get_json()["request"]["status"] == "approved"
    assert admin_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"] == 15


def test_rejecting_a_material_request_leaves_stock_untouched(app, client, admin_client, accounts_client):
    pid = make_project(client, admin_client)
    manager = make_user("Priya Manager", role="project_manager")
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    mat_id = stocked_material(admin_client)
    movement_id = accounts_client.post(f"/api/projects/{pid}/material-requests",
                                        json={"material_id": mat_id, "quantity": 5}).get_json()["request"]["id"]
    pm = signed_in(app, manager)
    res = pm.post(f"/api/projects/{pid}/material-requests/{movement_id}/reject")
    assert res.status_code == 200 and res.get_json()["request"]["status"] == "rejected"
    assert admin_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"] == 20


def test_material_requests_lists_pending_ones_and_who_can_approve(app, client, admin_client, accounts_client):
    pid = make_project(client, admin_client)
    manager = make_user("Priya Manager", role="project_manager")
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    mat_id = stocked_material(admin_client)
    accounts_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})

    pm = signed_in(app, manager)
    data = pm.get(f"/api/projects/{pid}/material-requests").get_json()
    assert len(data["requests"]) == 1 and data["requests"][0]["status"] == "pending"
    assert data["can_approve"] is True
    assert any(m["id"] == mat_id for m in data["materials"])

    data = accounts_client.get(f"/api/projects/{pid}/material-requests").get_json()
    assert data["can_approve"] is False                      # accounts can request, but not approve this one


def test_requesting_more_than_whats_in_stock_is_rejected(app, client, admin_client):
    pid = make_project(client, admin_client)
    mat_id = stocked_material(admin_client, qty=3)
    manager = make_user("Priya Manager", role="project_manager")
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    pm = signed_in(app, manager)
    res = pm.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})
    assert res.status_code == 422 and "quantity" in res.get_json()["fields"]

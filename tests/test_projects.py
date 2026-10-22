import io
from datetime import date
from decimal import Decimal

from app.constants import COMMISSION_ROLE_KEY, PROJECT_DOCUMENT_TYPES
from app.extensions import db
from app.models import Attendance, Client, Lead, Project, ProjectPayment, Role, RoleModule, Service, User, Worker, WorkerAttendance, utcnow
from conftest import make_user, signed_in, win_lead


def upload_all_documents(admin_client, pid):
    """Satisfy the closing-documents gate (app/projects.py's close_project) for tests that don't care
    about that gate itself - just want a project that's otherwise ready to close."""
    for doc_type, _label in PROJECT_DOCUMENT_TYPES:
        res = admin_client.post(f"/api/projects/{pid}/documents/{doc_type}",
                                 data={"file": (io.BytesIO(b"fake"), "doc.pdf", "application/pdf")},
                                 content_type="multipart/form-data")
        assert res.status_code == 201, res.get_json()


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


def contractor_fapa_user(app, name="Chandan Contractor"):
    """Contractor FAPA (kohal, 2026-10-19: "he needs to be given site supervisor access") - same module
    access as Site supervisor (projects + attendance, both write), set up directly in the database the same
    way kohal did on prod for this custom role (see app/roles.py's own docstring)."""
    if db.session.get(Role, "contractor_fapa") is None:
        db.session.add(Role(key="contractor_fapa", name="Contractor FAPA", sees_all=False))
        db.session.flush()
        for module_key in ("projects", "attendance"):
            db.session.add(RoleModule(role_key="contractor_fapa", module_key=module_key, write_access=True))
        db.session.flush()
    user = make_user(name, role="contractor_fapa")
    return signed_in(app, user), user


def test_contractor_fapa_only_sees_projects_theyve_checked_into(app, client, admin_client):
    """Same rule as Site supervisor itself (see SITE_SUPERVISOR_ROLE_KEYS) - a project only once they've
    actually checked Attendance into it, not by ownership/management."""
    visited = make_project(client, admin_client, company="Site They Visited")
    other = make_project(client, admin_client, company="Site They Never Went To")
    contractor_client, contractor = contractor_fapa_user(app)
    db.session.add(Attendance(user_code=contractor.code, work_date=date.today(),
                               project_id=visited, check_in_at=utcnow()))
    db.session.commit()
    assert [p["id"] for p in contractor_client.get("/api/projects").get_json()["projects"]] == [visited]
    assert contractor_client.get(f"/api/projects/{visited}").status_code == 200
    assert contractor_client.get(f"/api/projects/{other}").status_code == 404


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


def test_a_pending_check_in_does_not_count_toward_the_teams_days(app, client, admin_client, user):
    """kohal, 2026-10-16: a check-in needs approval (see Attendance.status) - until then it isn't a verified
    day's work, so it's left off the project's own team/days tally."""
    pid = make_project(client, admin_client)
    res = client.post("/api/attendance/check-in", json={"lat": 21.1458, "lng": 79.0882, "project_id": pid})
    assert res.get_json()["today"]["status"] == "pending"
    dash = admin_client.get(f"/api/projects/{pid}").get_json()["dashboard"]
    assert dash["team"] == []

    with app.app_context():
        row = Attendance.query.filter_by(user_code=user.code, project_id=pid).first()
        row.status = "approved"
        db.session.commit()
    dash = admin_client.get(f"/api/projects/{pid}").get_json()["dashboard"]
    assert [(m["name"], m["days"]) for m in dash["team"]] == [(user.name, 1)]


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


def test_the_progress_tab_flag_is_admin_only(client, admin_client, accounts_client):
    """kohal, 2026-10-22: "a new subtab in projects called progress... visible only to admin and client
    role" - on this side (the admin-facing project detail page), that just means the flag the frontend
    uses to show/hide the tab chip (app/static/js/projects.js), nothing else sees it true. A client's own
    matching view is entirely separate - see tests/test_client_portal.py."""
    pid = make_project(client, admin_client)
    assert admin_client.get(f"/api/projects/{pid}").get_json()["dashboard"]["can_see_progress"] is True
    assert accounts_client.get(f"/api/projects/{pid}").get_json()["dashboard"]["can_see_progress"] is False


# ---------- Progress tab: the fixed installation stage checklist ----------
# (kohal, 2026-10-22: "stages of project, work pics at each phase... admin will set the days and mark done")

STAGE_KEYS = [
    "commencement", "riser_installation", "sprinkler_installation", "alarm_cabling",
    "fire_equipment_installation", "pump_installation", "testing_commissioning",
    "portable_device_installation", "handover",
]


def test_every_project_starts_with_the_same_nine_untouched_stages(client, admin_client):
    pid = make_project(client, admin_client)
    stages = admin_client.get(f"/api/projects/{pid}").get_json()["stages"]
    assert [s["key"] for s in stages] == STAGE_KEYS
    assert all(s["days"] is None and s["done"] is False and s["completed_at"] is None and s["photos"] == [] for s in stages)
    assert stages[0]["note"] == "Provision, estimate, building diagram"


def test_only_the_admin_can_update_a_stage(client, admin_client, accounts_client, manager_client):
    pid = make_project(client, admin_client)
    for who in (accounts_client, manager_client):
        res = who.patch(f"/api/projects/{pid}/stages/commencement", json={"days": 5})
        assert res.status_code == 403


def test_unknown_stage_key_is_rejected(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Bad Stage Key"}).get_json()["project"]["id"]
    assert admin_client.patch(f"/api/projects/{pid}/stages/not_a_real_stage", json={"days": 5}).status_code == 404
    res = admin_client.post(f"/api/projects/{pid}/stages/not_a_real_stage/photos",
                             data={"photos": (io.BytesIO(b"fake"), "p.jpg", "image/jpeg")},
                             content_type="multipart/form-data")
    assert res.status_code == 404


def test_setting_a_stages_planned_days(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Stage Days"}).get_json()["project"]["id"]
    res = admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"days": 4})
    assert res.status_code == 200
    stages = {s["key"]: s for s in res.get_json()["stages"]}
    assert stages["commencement"]["days"] == 4

    cleared = admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"days": None})
    stages2 = {s["key"]: s for s in cleared.get_json()["stages"]}
    assert stages2["commencement"]["days"] is None

    assert admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"days": 400}).status_code == 422


def test_marking_a_stage_done_sets_and_clears_completed_at(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Stage Done"}).get_json()["project"]["id"]
    done = admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"done": True})
    stages = {s["key"]: s for s in done.get_json()["stages"]}
    assert stages["commencement"]["done"] is True and stages["commencement"]["completed_at"] is not None

    undone = admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"done": False})
    stages2 = {s["key"]: s for s in undone.get_json()["stages"]}
    assert stages2["commencement"]["done"] is False and stages2["commencement"]["completed_at"] is None


# ---------- one stage at a time, like a lead's own Lead.stage (kohal, 2026-10-22: "follow the same
# template as lead, only when mark done of current stage then only goto next stage") ----------

def test_the_current_stage_is_the_first_not_done_one_and_moves_forward_as_stages_complete(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Stage Order"}).get_json()["project"]["id"]
    detail = admin_client.get(f"/api/projects/{pid}").get_json()
    assert detail["current_stage_key"] == "commencement"

    after = admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"done": True}).get_json()
    assert after["current_stage_key"] == "riser_installation"


def test_a_later_stage_cannot_be_marked_done_before_the_current_one(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Out Of Order"}).get_json()["project"]["id"]
    res = admin_client.patch(f"/api/projects/{pid}/stages/handover", json={"done": True})
    assert res.status_code == 422
    stages = {s["key"]: s for s in admin_client.get(f"/api/projects/{pid}").get_json()["stages"]}
    assert stages["handover"]["done"] is False


def test_a_future_stages_days_cannot_be_set_before_its_turn(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Future Days"}).get_json()["project"]["id"]
    res = admin_client.patch(f"/api/projects/{pid}/stages/riser_installation", json={"days": 3})
    assert res.status_code == 422


# ---------- a free note on the current stage (kohal, 2026-10-22: "add note at each step") ----------

def test_setting_a_note_on_the_current_stage(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Stage Note"}).get_json()["project"]["id"]
    res = admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"remarks": "Client site visit done"})
    assert res.status_code == 200
    stages = {s["key"]: s for s in res.get_json()["stages"]}
    assert stages["commencement"]["remarks"] == "Client site visit done"

    cleared = admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"remarks": ""})
    stages2 = {s["key"]: s for s in cleared.get_json()["stages"]}
    assert stages2["commencement"]["remarks"] == ""


def test_a_future_stages_note_cannot_be_set_before_its_turn(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Future Note"}).get_json()["project"]["id"]
    res = admin_client.patch(f"/api/projects/{pid}/stages/riser_installation", json={"remarks": "Too soon"})
    assert res.status_code == 422


def test_a_finished_stages_note_stays_visible(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Finished Note"}).get_json()["project"]["id"]
    admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"remarks": "All good"})
    done = admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"done": True})
    stages = {s["key"]: s for s in done.get_json()["stages"]}
    assert stages["commencement"]["remarks"] == "All good"


def test_only_the_most_recently_completed_stage_can_be_reopened(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Reopen Order"}).get_json()["project"]["id"]
    admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"done": True})
    admin_client.patch(f"/api/projects/{pid}/stages/riser_installation", json={"done": True})

    # commencement is done but no longer the most recent completion (riser_installation is) - reopening
    # it now would leave a gap, so it's refused; the actual most recent one can still be undone.
    blocked = admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"done": False})
    assert blocked.status_code == 422
    ok = admin_client.patch(f"/api/projects/{pid}/stages/riser_installation", json={"done": False})
    assert ok.status_code == 200
    assert ok.get_json()["current_stage_key"] == "riser_installation"


def test_marking_all_nine_stages_done_leaves_no_current_stage(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "All Done"}).get_json()["project"]["id"]
    last = None
    for key in STAGE_KEYS:
        last = admin_client.patch(f"/api/projects/{pid}/stages/{key}", json={"done": True}).get_json()
    assert last["current_stage_key"] is None


# ---------- pausing the current stage with a reason ----------
# (kohal, 2026-10-22: "add pause button after each stage. if paused then whats the reason? payment not
# recieved, manpower shortage, material shortage")

def test_only_the_admin_can_pause_or_resume_a_stage(client, admin_client, accounts_client, manager_client):
    pid = make_project(client, admin_client)
    for who in (accounts_client, manager_client):
        assert who.post(f"/api/projects/{pid}/stages/commencement/pause", json={"reason": "manpower_shortage"}).status_code == 403
    admin_client.post(f"/api/projects/{pid}/stages/commencement/pause", json={"reason": "manpower_shortage"})
    for who in (accounts_client, manager_client):
        assert who.post(f"/api/projects/{pid}/stages/commencement/resume").status_code == 403


def test_only_the_current_stage_can_be_paused(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Pause Order"}).get_json()["project"]["id"]
    res = admin_client.post(f"/api/projects/{pid}/stages/riser_installation/pause", json={"reason": "material_shortage"})
    assert res.status_code == 422


def test_pausing_needs_a_known_reason(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Bad Reason"}).get_json()["project"]["id"]
    assert admin_client.post(f"/api/projects/{pid}/stages/commencement/pause", json={}).status_code == 422
    assert admin_client.post(f"/api/projects/{pid}/stages/commencement/pause", json={"reason": "not_a_reason"}).status_code == 422


def test_pausing_for_other_needs_a_note(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Other Reason"}).get_json()["project"]["id"]
    blocked = admin_client.post(f"/api/projects/{pid}/stages/commencement/pause", json={"reason": "other"})
    assert blocked.status_code == 422
    ok = admin_client.post(f"/api/projects/{pid}/stages/commencement/pause", json={"reason": "other", "note": "Site access blocked"})
    assert ok.status_code == 200
    stages = {s["key"]: s for s in ok.get_json()["stages"]}
    assert stages["commencement"]["pause_note"] == "Site access blocked"


def test_pause_and_resume_round_trip(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Pause Lifecycle"}).get_json()["project"]["id"]
    paused = admin_client.post(f"/api/projects/{pid}/stages/commencement/pause", json={"reason": "payment_not_received"})
    stages = {s["key"]: s for s in paused.get_json()["stages"]}
    assert stages["commencement"]["paused"] is True
    assert stages["commencement"]["pause_reason"] == "payment_not_received"
    assert stages["commencement"]["paused_at"] is not None

    resumed = admin_client.post(f"/api/projects/{pid}/stages/commencement/resume")
    assert resumed.status_code == 200
    stages2 = {s["key"]: s for s in resumed.get_json()["stages"]}
    assert stages2["commencement"]["paused"] is False
    assert stages2["commencement"]["pause_reason"] is None
    assert stages2["commencement"]["paused_at"] is None

    assert admin_client.post(f"/api/projects/{pid}/stages/commencement/resume").status_code == 422


def test_a_paused_stage_cannot_be_marked_done(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Paused Done"}).get_json()["project"]["id"]
    admin_client.post(f"/api/projects/{pid}/stages/commencement/pause", json={"reason": "manpower_shortage"})
    blocked = admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"done": True})
    assert blocked.status_code == 422
    admin_client.post(f"/api/projects/{pid}/stages/commencement/resume")
    assert admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"done": True}).status_code == 200


def test_photo_upload_is_blocked_on_a_non_current_stage(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Future Photo"}).get_json()["project"]["id"]
    res = admin_client.post(f"/api/projects/{pid}/stages/riser_installation/photos",
                             data={"photos": (io.BytesIO(b"fake"), "p.jpg", "image/jpeg")},
                             content_type="multipart/form-data")
    assert res.status_code == 422


def test_only_the_admin_can_upload_or_remove_a_stage_photo(client, admin_client, accounts_client, manager_client):
    pid = make_project(client, admin_client)
    for who in (accounts_client, manager_client):
        res = who.post(f"/api/projects/{pid}/stages/commencement/photos",
                        data={"photos": (io.BytesIO(b"fake"), "p.jpg", "image/jpeg")},
                        content_type="multipart/form-data")
        assert res.status_code == 403
    admin_client.post(f"/api/projects/{pid}/stages/commencement/photos",
                       data={"photos": (io.BytesIO(b"fake"), "p.jpg", "image/jpeg")},
                       content_type="multipart/form-data")
    assert accounts_client.delete(f"/api/projects/{pid}/stages/commencement/photos/1").status_code == 403


def test_stage_photo_upload_and_removal(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Stage Photos"}).get_json()["project"]["id"]
    uploaded = admin_client.post(f"/api/projects/{pid}/stages/commencement/photos",
                                  data={"photos": (io.BytesIO(b"fake"), "p.jpg", "image/jpeg")},
                                  content_type="multipart/form-data")
    assert uploaded.status_code == 201
    stages = {s["key"]: s for s in uploaded.get_json()["stages"]}
    photos = stages["commencement"]["photos"]
    assert len(photos) == 1 and photos[0]["url"]
    photo_id = photos[0]["id"]

    removed = admin_client.delete(f"/api/projects/{pid}/stages/commencement/photos/{photo_id}")
    assert removed.status_code == 200
    stages2 = {s["key"]: s for s in removed.get_json()["stages"]}
    assert stages2["commencement"]["photos"] == []


def test_uploading_a_stage_photo_requires_at_least_one_file(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "No Photo"}).get_json()["project"]["id"]
    assert admin_client.post(f"/api/projects/{pid}/stages/commencement/photos", data={}).status_code == 422


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
    # Fully paid now, but the 3 closing documents aren't on file yet - still refused.
    still_blocked2 = admin_client.post(f"/api/projects/{pid}/close")
    assert still_blocked2.status_code == 422

    upload_all_documents(admin_client, pid)
    closed = admin_client.post(f"/api/projects/{pid}/close")
    assert closed.status_code == 200
    body = closed.get_json()
    assert body["project"]["status"] == "completed" and body["dashboard"]["completed_at"].endswith("Z")
    assert admin_client.post(f"/api/projects/{pid}/close").status_code == 409


# ---------- closing documents: final estimate, work completion certificate, final invoice ----------
# (kohal, 2026-10-21: "need to mandatorily upload these 3 things once measure done = true")

def test_only_the_admin_can_upload_or_remove_a_closing_document(client, admin_client, accounts_client, manager_client):
    pid = make_project(client, admin_client)
    for who in (accounts_client, manager_client):
        res = who.post(f"/api/projects/{pid}/documents/final_estimate",
                        data={"file": (io.BytesIO(b"fake"), "doc.pdf", "application/pdf")},
                        content_type="multipart/form-data")
        assert res.status_code == 403
    admin_client.post(f"/api/projects/{pid}/documents/final_estimate",
                       data={"file": (io.BytesIO(b"fake"), "doc.pdf", "application/pdf")},
                       content_type="multipart/form-data")
    assert accounts_client.delete(f"/api/projects/{pid}/documents/final_estimate").status_code == 403


def test_unknown_document_type_is_rejected(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Doc Type Check"}).get_json()["project"]["id"]
    res = admin_client.post(f"/api/projects/{pid}/documents/some_other_thing",
                             data={"file": (io.BytesIO(b"fake"), "doc.pdf", "application/pdf")},
                             content_type="multipart/form-data")
    assert res.status_code == 404


def test_uploading_a_document_requires_a_file(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "No File"}).get_json()["project"]["id"]
    assert admin_client.post(f"/api/projects/{pid}/documents/final_estimate", data={}).status_code == 422


def test_document_upload_shows_up_on_the_project_and_can_be_replaced_or_removed(admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Doc Lifecycle"}).get_json()["project"]["id"]
    res = admin_client.post(f"/api/projects/{pid}/documents/final_invoice",
                             data={"file": (io.BytesIO(b"fake"), "invoice.pdf", "application/pdf")},
                             content_type="multipart/form-data")
    assert res.status_code == 201
    docs = res.get_json()["project"]["documents"]
    assert set(docs) == {"final_invoice"} and docs["final_invoice"]["url"]
    first_url = docs["final_invoice"]["url"]

    # Re-uploading the same type replaces it rather than adding a second entry.
    replaced = admin_client.post(f"/api/projects/{pid}/documents/final_invoice",
                                  data={"file": (io.BytesIO(b"fake2"), "invoice2.pdf", "application/pdf")},
                                  content_type="multipart/form-data").get_json()
    docs2 = replaced["project"]["documents"]
    assert len(docs2) == 1 and docs2["final_invoice"]["url"] != first_url

    cleared = admin_client.delete(f"/api/projects/{pid}/documents/final_invoice").get_json()
    assert cleared["project"]["documents"] == {}


def test_closing_is_blocked_until_all_three_documents_are_on_file(client, admin_client):
    pid = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid}", json={
        "title": "T", "final_amount": 100000,
        "payments": [{"label": "Final", "amount": 100000, "mode": "Cash", "paid_date": "2026-09-30"}],
    })
    for doc_type, _label in PROJECT_DOCUMENT_TYPES[:-1]:
        admin_client.post(f"/api/projects/{pid}/documents/{doc_type}",
                           data={"file": (io.BytesIO(b"fake"), "doc.pdf", "application/pdf")},
                           content_type="multipart/form-data")
    res = admin_client.post(f"/api/projects/{pid}/close")
    assert res.status_code == 422
    assert PROJECT_DOCUMENT_TYPES[-1][1] in res.get_json()["error"]

    last_type = PROJECT_DOCUMENT_TYPES[-1][0]
    admin_client.post(f"/api/projects/{pid}/documents/{last_type}",
                       data={"file": (io.BytesIO(b"fake"), "doc.pdf", "application/pdf")},
                       content_type="multipart/form-data")
    assert admin_client.post(f"/api/projects/{pid}/close").status_code == 200


def test_completed_at_follows_the_status_when_edited(client, admin_client):
    pid = make_project(client, admin_client)
    url = f"/api/projects/{pid}"
    assert admin_client.patch(url, json={"title": "T", "status": "completed"}).status_code == 422
    blocked = admin_client.patch(url, json={
        "title": "T", "status": "completed", "final_amount": 100000,
        "payments": [{"label": "Final", "amount": 100000, "mode": "Cash", "paid_date": "2026-09-30"}],
    })
    assert blocked.status_code == 422                # measured and paid, but no closing documents yet
    upload_all_documents(admin_client, pid)
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

def add_material_and_issue(app, admin_client, project_id, name="Cement", quantity=10, rate=50):
    """An approved issue against this project - a material request now, the only way one can exist (kohal,
    2026-10-19: "even issue to project should have the same process as material request" - the old direct-
    issue-from-Inventory shortcut is gone), approved by someone other than the admin who asked for it, since
    the requester can never approve their own."""
    material = admin_client.post("/api/inventory/materials", json={"name": name, "unit": "bags"}).get_json()["material"]
    admin_client.post(f"/api/inventory/materials/{material['id']}/stock-in", json={"quantity": quantity * 10, "rate": rate})
    req = admin_client.post(f"/api/projects/{project_id}/material-requests",
                             json={"material_id": material["id"], "quantity": quantity, "note": "Foundation work"})
    assert req.status_code == 201, req.get_json()
    movement_id = req.get_json()["request"]["id"]
    with app.app_context():
        worker = Worker(name=f"Storekeeper {movement_id}")
        db.session.add(worker)
        db.session.commit()
        worker_id = worker.id
    approver = signed_in(app, make_user(f"Approver {movement_id}", role="accounts"))
    res = approver.post(f"/api/inventory/material-requests/{movement_id}/approve", json={
        "quantity": quantity, "given_by_worker_id": worker_id, "transport_mode": "Own vehicle",
    })
    assert res.status_code == 200, res.get_json()
    return material


def test_project_detail_lists_materials_issued_to_it_and_their_total_cost(app, admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Site With Materials"}).get_json()["project"]["id"]
    add_material_and_issue(app, admin_client, pid, "Cement", quantity=10, rate=50)
    add_material_and_issue(app, admin_client, pid, "TMT Bars", quantity=5, rate=60)

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


def test_materials_issued_to_a_different_project_do_not_show_up(app, admin_client):
    pid1 = admin_client.post("/api/projects", json={"new_client_name": "Project One"}).get_json()["project"]["id"]
    pid2 = admin_client.post("/api/projects", json={"new_client_name": "Project Two"}).get_json()["project"]["id"]
    add_material_and_issue(app, admin_client, pid1, "Cement", quantity=10, rate=50)
    detail = admin_client.get(f"/api/projects/{pid2}").get_json()
    assert detail["materials"] == []


def test_a_closed_project_can_still_be_deleted(client, admin_client):
    """TEMPORARY - closed/completed projects need the backfill cleanup too."""
    pid = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid}", json={
        "title": "T", "final_amount": 100000,
        "payments": [{"label": "Final", "amount": 100000, "mode": "Cash", "paid_date": "2026-09-30"}],
    })
    upload_all_documents(admin_client, pid)
    assert admin_client.post(f"/api/projects/{pid}/close").status_code == 200
    dash = admin_client.get(f"/api/projects/{pid}").get_json()["dashboard"]
    assert dash["can_delete"] is True
    assert admin_client.delete(f"/api/projects/{pid}").status_code == 204


# ---------- material requests (kohal, 2026-10-16, eligibility updated 2026-10-17) ----------
#
# Asking for material against a project lives here; approving one doesn't any more - see
# test_inventory.py's "Material requests" section for that (app/inventory.py's own tab, "anyone with
# Inventory access can approve", kohal, 2026-10-17).

def stocked_material(admin_client, qty=20, name="Cement"):
    res = admin_client.post("/api/inventory/materials", json={"name": name, "unit": "bags", "quantity": qty, "rate": 10})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["material"]["id"]


def test_a_request_from_someone_with_inventory_access_still_waits_too(app, client, admin_client, accounts_client):
    """kohal, 2026-10-19: "it should not be auto approved... creator user cannot be approval" - no more
    self-approval shortcut for anyone, not even an accountant who could otherwise approve someone else's."""
    pid = make_project(client, admin_client)
    mat_id = stocked_material(admin_client)
    res = accounts_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})
    assert res.status_code == 201
    body = res.get_json()["request"]
    assert body["status"] == "pending" and body["approved_by_name"] is None
    assert admin_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"] == 20


def test_a_request_from_the_projects_own_manager_now_waits_too(app, client, admin_client):
    """kohal, 2026-10-17: a project manager used to auto-approve their own project's request - that moved
    to Inventory access only, so even the project's own manager now waits, same as anyone else without it."""
    pid = make_project(client, admin_client)
    manager = make_user("Priya Manager", role="project_manager")
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    mat_id = stocked_material(admin_client)
    pm = signed_in(app, manager)

    res = pm.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})
    assert res.status_code == 201
    body = res.get_json()["request"]
    assert body["status"] == "pending" and body["approved_by_name"] is None
    assert admin_client.get(f"/api/inventory/materials/{mat_id}").get_json()["material"]["stock_qty"] == 20  # untouched


# "if the requested material is not present in inventory, its showing this error, it shouldnt. if not in
# inventory, it should go to inventory restock" (kohal, 2026-10-21) - typing a name no Material row matches
# yet adds it to the catalog on the spot (0 stock) instead of refusing the request, so the shortfall
# surfaces on Restock (test_inventory.py's own Restock section) like any other.

def test_requesting_an_unlisted_material_by_name_creates_it(client, admin_client):
    pid = make_project(client, admin_client)
    res = admin_client.post(f"/api/projects/{pid}/material-requests",
                             json={"material_name": "Branch Pipe", "quantity": 5})
    assert res.status_code == 201
    body = res.get_json()["request"]
    assert body["status"] == "pending" and body["material_name"] == "Branch Pipe"
    material = admin_client.get("/api/inventory/materials").get_json()["materials"]
    row = next(m for m in material if m["name"] == "Branch Pipe")
    assert row["stock_qty"] == 0


def test_requesting_an_unlisted_material_with_no_name_still_fails(client, admin_client):
    pid = make_project(client, admin_client)
    res = admin_client.post(f"/api/projects/{pid}/material-requests", json={"quantity": 5})
    assert res.status_code == 422 and "material_id" in res.get_json()["fields"]


def test_requesting_by_name_reuses_an_existing_material_case_insensitively(client, admin_client):
    pid = make_project(client, admin_client)
    mat_id = stocked_material(admin_client, qty=20, name="Cement")
    res = admin_client.post(f"/api/projects/{pid}/material-requests",
                             json={"material_name": "cement", "quantity": 5})
    assert res.status_code == 201
    assert res.get_json()["request"]["material_id"] == mat_id
    assert len(admin_client.get("/api/inventory/materials").get_json()["materials"]) == 1  # no duplicate


def test_a_return_cannot_create_a_new_material_by_name(client, admin_client):
    pid = make_project(client, admin_client)
    res = admin_client.post(f"/api/projects/{pid}/material-requests",
                             json={"material_name": "Never Issued", "quantity": 5, "kind": "in"})
    assert res.status_code == 422 and "material_id" in res.get_json()["fields"]
    assert admin_client.get("/api/inventory/materials").get_json()["materials"] == []


def test_a_supervisor_not_checked_in_there_cant_even_see_the_project(app, client, admin_client):
    """visible_projects() already hides a project from a site supervisor until they've checked into it, so
    there's nothing to request here in the first place - not a 403, a 404, same as everywhere else that
    scoping applies. (Checking in no longer changes whether their own request is approved - see
    test_inventory.py - but it's still how they get to see the project at all.)"""
    pid = make_project(client, admin_client)
    mat_id = stocked_material(admin_client)
    supervisor = make_user("Site Sam", role="supervisor")
    sup_client = signed_in(app, supervisor)
    res = sup_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})
    assert res.status_code == 404


def test_material_requests_lists_pending_ones_for_the_project(app, client, admin_client, accounts_client):
    pid = make_project(client, admin_client)
    manager = make_user("Priya Manager", role="project_manager")
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    mat_id = stocked_material(admin_client)
    pm = signed_in(app, manager)
    pm.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})

    data = pm.get(f"/api/projects/{pid}/material-requests").get_json()
    assert len(data["requests"]) == 1 and data["requests"][0]["status"] == "pending"
    assert any(m["id"] == mat_id for m in data["materials"])
    assert "can_approve" not in data        # approving moved to Inventory - nothing to decide here now


def test_requesting_more_than_whats_in_stock_is_fine_if_it_waits_for_approval(app, client, admin_client):
    """kohal, 2026-10-17: "say if stock has 5 pipes and request was raised for 7 pipes" - that's the whole
    point of a request someone else approves (see test_inventory.py's "Material requests" section for the
    partial-approval/shortfall handling) - a request always waits now (see the next test), so there's no
    "approved on the spot" path left to cap this against."""
    pid = make_project(client, admin_client)
    mat_id = stocked_material(admin_client, qty=3)
    manager = make_user("Priya Manager", role="project_manager")
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": manager.code})
    pm = signed_in(app, manager)
    res = pm.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})
    assert res.status_code == 201 and res.get_json()["request"]["status"] == "pending"


def test_requesting_more_than_stock_is_fine_for_anyone_now_it_always_waits(app, client, admin_client, accounts_client):
    """Same as the plain-sales-field case above - there's no "approved on the spot" path left for a
    material request to overshoot through, so there's nothing left to cap here either."""
    pid = make_project(client, admin_client)
    mat_id = stocked_material(admin_client, qty=3)
    res = accounts_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 5})
    assert res.status_code == 201 and res.get_json()["request"]["status"] == "pending"


# ---------- return to inventory (kohal, 2026-10-20) ----------
#
# "whatever material is requested by the site supervisor, some of them are not used in the project, so
# there should be a return to inventory request as well but the quantity and material source will be
# whatever is present in the project" - a return is a `kind: "in"` request, capped at how much of that
# material is still out at this project (approved issues minus whatever's already come back).

def test_no_returnable_materials_until_something_has_actually_been_issued(client, admin_client):
    pid = make_project(client, admin_client)
    data = admin_client.get(f"/api/projects/{pid}/material-requests").get_json()
    assert data["returnable_materials"] == []


def test_returnable_materials_lists_whats_still_out_at_the_project(app, admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Returnable Site"}).get_json()["project"]["id"]
    material = add_material_and_issue(app, admin_client, pid, "Cement", quantity=10, rate=50)
    data = admin_client.get(f"/api/projects/{pid}/material-requests").get_json()
    row = next(m for m in data["returnable_materials"] if m["id"] == material["id"])
    assert row["returnable_qty"] == 10 and row["code"] == material["code"]


def test_requesting_a_return_for_more_than_whats_out_is_rejected(app, admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Over-return Site"}).get_json()["project"]["id"]
    material = add_material_and_issue(app, admin_client, pid, "Cement", quantity=10, rate=50)
    res = admin_client.post(f"/api/projects/{pid}/material-requests",
                             json={"material_id": material["id"], "quantity": 11, "kind": "in"})
    assert res.status_code == 422 and "quantity" in res.get_json()["fields"]


def test_requesting_a_return_within_whats_out_waits_for_approval(app, admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Within-return Site"}).get_json()["project"]["id"]
    material = add_material_and_issue(app, admin_client, pid, "Cement", quantity=10, rate=50)
    res = admin_client.post(f"/api/projects/{pid}/material-requests",
                             json={"material_id": material["id"], "quantity": 10, "kind": "in"})
    assert res.status_code == 201
    body = res.get_json()["request"]
    assert body["status"] == "pending" and body["kind"] == "in"


def test_a_material_never_issued_to_the_project_cannot_be_returned(app, admin_client):
    pid = admin_client.post("/api/projects", json={"new_client_name": "Nothing Issued Site"}).get_json()["project"]["id"]
    mat_id = stocked_material(admin_client, qty=20, name="Sand")
    res = admin_client.post(f"/api/projects/{pid}/material-requests", json={"material_id": mat_id, "quantity": 1, "kind": "in"})
    assert res.status_code == 422 and "quantity" in res.get_json()["fields"]


def test_the_materials_list_shows_a_returned_amount_as_a_negative_cost(app, admin_client):
    """So the project's own total material cost nets out (issued minus returned) without any separate
    subtraction logic on the frontend (kohal, 2026-10-20)."""
    pid = admin_client.post("/api/projects", json={"new_client_name": "Netted Cost Site"}).get_json()["project"]["id"]
    material = add_material_and_issue(app, admin_client, pid, "Cement", quantity=10, rate=50)
    req = admin_client.post(f"/api/projects/{pid}/material-requests",
                             json={"material_id": material["id"], "quantity": 4, "kind": "in"})
    movement_id = req.get_json()["request"]["id"]
    approver = signed_in(app, make_user("Returns Approver", role="accounts"))
    with app.app_context():
        wid = Worker(name="Returns Storekeeper")
        db.session.add(wid)
        db.session.commit()
        wid = wid.id
    res = approver.post(f"/api/inventory/material-requests/{movement_id}/approve",
                         json={"quantity": 4, "given_by_worker_id": wid, "transport_mode": "Own vehicle"})
    assert res.status_code == 200, res.get_json()

    detail = admin_client.get(f"/api/projects/{pid}").get_json()
    assert detail["total_material_cost"] == 300           # 10*50 issued - 4*50 returned
    returned_row = next(m for m in detail["materials"] if m["kind"] == "in")
    assert returned_row["amount"] == -200


# ---------- Commission (kohal, 2026-10-18) ----------
#
# "the person assigned to [Project manager Chandrapur] gets commission on the negotiated amount of the
# project... what percentage of commission was given to whom and that should go towards project expense".

def commission_worker(name="Chetan Chandrapur"):
    """A Worker in the commission role - not seeded by default (see conftest.seed_reference_data), since
    it's a role kohal added on prod via Users & roles, not one built into this codebase's reference data."""
    if db.session.get(Role, COMMISSION_ROLE_KEY) is None:
        db.session.add(Role(key=COMMISSION_ROLE_KEY, name="Project manager Chandrapur", sees_all=False))
        db.session.flush()
    worker = Worker(name=name, category="staff", role_key=COMMISSION_ROLE_KEY)
    db.session.add(worker)
    db.session.commit()
    return worker.id


def project_with_amount(client, admin_client, amount):
    """A project with a specific negotiated amount - win_lead's own negotiation round is fixed at
    1,000,000 (see its docstring), so the amount is set directly here instead, the same way the Payment
    tab's own "Fill amount" button does it."""
    pid = make_project(client, admin_client)
    res = admin_client.patch(f"/api/projects/{pid}", json={"estimated_amount": amount})
    assert res.status_code == 200, res.get_json()
    return pid


def test_commission_is_computed_from_the_negotiated_amount(app, client, admin_client):
    pid = project_with_amount(client, admin_client, 200000)   # net_amount = 200000 (no discount/final)
    with app.app_context():
        wid = commission_worker()
    res = admin_client.post(f"/api/projects/{pid}/expenses", json={"worker_id": wid, "percent": "5"})
    assert res.status_code == 201
    body = res.get_json()
    assert len(body["expenses"]) == 1
    e = body["expenses"][0]
    assert e["percent"] == 5.0 and e["basis_amount"] == 200000.0 and e["amount"] == 10000.0
    assert e["kind"] == "commission" and e["worker_name"] == "Chetan Chandrapur"
    assert body["total_expense"] == 10000.0


def test_commission_can_only_go_to_someone_in_the_chandrapur_role(app, client, admin_client):
    pid = project_with_amount(client, admin_client, 200000)
    with app.app_context():
        other = Worker(name="Wendy Welder", category="manpower", role_key="welder")
        db.session.add(other)
        db.session.commit()
        wid = other.id
    res = admin_client.post(f"/api/projects/{pid}/expenses", json={"worker_id": wid, "percent": "5"})
    assert res.status_code == 422 and "worker_id" in res.get_json()["fields"]


def test_commission_percent_must_be_a_sane_percentage(app, client, admin_client):
    pid = project_with_amount(client, admin_client, 200000)
    with app.app_context():
        wid = commission_worker()
    for bad in ("0", "-5", "101", "abc", ""):
        res = admin_client.post(f"/api/projects/{pid}/expenses", json={"worker_id": wid, "percent": bad})
        assert res.status_code == 422 and "percent" in res.get_json()["fields"], bad


def test_commission_needs_the_projects_amount_set_first(app, admin_client):
    res = admin_client.post("/api/projects", json={"new_client_name": "No Amount Yet"})
    pid = res.get_json()["project"]["id"]
    with app.app_context():
        wid = commission_worker()
    res = admin_client.post(f"/api/projects/{pid}/expenses", json={"worker_id": wid, "percent": "5"})
    assert res.status_code == 422 and "percent" in res.get_json()["fields"]


def test_commission_amount_is_a_snapshot_not_live(app, client, admin_client):
    """kohal, 2026-10-18 (answered): "Snapshot at entry time" - a later change to the project's own
    negotiated amount must not silently move money already recorded as paid out."""
    pid = project_with_amount(client, admin_client, 200000)
    with app.app_context():
        wid = commission_worker()
    expense_id = admin_client.post(f"/api/projects/{pid}/expenses",
                                    json={"worker_id": wid, "percent": "5"}).get_json()["expenses"][0]["id"]
    admin_client.patch(f"/api/projects/{pid}", json={"estimated_amount": 400000})
    data = admin_client.get(f"/api/projects/{pid}").get_json()
    e = next(x for x in data["expenses"] if x["id"] == expense_id)
    assert e["basis_amount"] == 200000.0 and e["amount"] == 10000.0   # unchanged by the amount edit above


def test_editing_a_commission_entry_resnapshots_against_the_current_amount(app, client, admin_client):
    pid = project_with_amount(client, admin_client, 200000)
    with app.app_context():
        wid = commission_worker()
    expense_id = admin_client.post(f"/api/projects/{pid}/expenses",
                                    json={"worker_id": wid, "percent": "5"}).get_json()["expenses"][0]["id"]
    admin_client.patch(f"/api/projects/{pid}", json={"estimated_amount": 400000})
    res = admin_client.patch(f"/api/projects/{pid}/expenses/{expense_id}", json={"worker_id": wid, "percent": "10"})
    assert res.status_code == 200
    e = next(x for x in res.get_json()["expenses"] if x["id"] == expense_id)
    assert e["basis_amount"] == 400000.0 and e["amount"] == 40000.0


def test_deleting_a_commission_entry(app, client, admin_client):
    pid = project_with_amount(client, admin_client, 200000)
    with app.app_context():
        wid = commission_worker()
    expense_id = admin_client.post(f"/api/projects/{pid}/expenses",
                                    json={"worker_id": wid, "percent": "5"}).get_json()["expenses"][0]["id"]
    res = admin_client.delete(f"/api/projects/{pid}/expenses/{expense_id}")
    assert res.status_code == 200 and res.get_json()["expenses"] == []
    assert res.get_json()["total_expense"] == 0


def test_commission_workers_lists_only_the_chandrapur_role(app, client, admin_client):
    pid = project_with_amount(client, admin_client, 200000)
    with app.app_context():
        wid = commission_worker()
        db.session.add(Worker(name="Wendy Welder", category="manpower", role_key="welder"))
        db.session.commit()
    data = admin_client.get(f"/api/projects/{pid}").get_json()
    assert [w["id"] for w in data["commission_workers"]] == [wid]


# ---------- Daily-wage expense (kohal, 2026-10-20) ----------
#
# "now we go to calculating the woker expense for each project... if the worker checks in project 1 on day
# 1,2,3, then the total expense will be = (dailiy wages*3)" - computed straight from attendance, never a
# manual entry like commission; see app/projects.py's _wage_expenses.

def daily_wage_worker(name="Deepak Daily", wage_amount=Decimal("500"), user_code=None):
    worker = Worker(name=name, category="manpower", employment_type="daily_wages",
                     wage_amount=wage_amount, user_code=user_code)
    db.session.add(worker)
    db.session.commit()
    return worker


def test_daily_wage_expense_is_days_checked_in_times_the_wage(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        worker = daily_wage_worker(wage_amount=Decimal("500"))
        for d in (1, 2, 3):
            db.session.add(WorkerAttendance(worker=worker, work_date=date(2026, 10, d), project_id=pid))
        db.session.commit()
        wid = worker.id
    data = admin_client.get(f"/api/projects/{pid}").get_json()
    assert data["wage_expenses"] == [
        {"worker_id": wid, "worker_name": "Deepak Daily", "days": 3, "wage_amount": 500.0, "amount": 1500.0},
    ]
    assert data["total_wage_expense"] == 1500.0


def test_daily_wage_expense_ignores_absent_days_and_other_projects(app, client, admin_client):
    pid = make_project(client, admin_client)
    other_pid = make_project(client, admin_client)
    with app.app_context():
        worker = daily_wage_worker()
        db.session.add(WorkerAttendance(worker=worker, work_date=date(2026, 10, 1), project_id=pid))
        db.session.add(WorkerAttendance(worker=worker, work_date=date(2026, 10, 2), project_id=pid, status="absent"))
        db.session.add(WorkerAttendance(worker=worker, work_date=date(2026, 10, 3), project_id=other_pid))
        db.session.commit()
    data = admin_client.get(f"/api/projects/{pid}").get_json()
    assert data["wage_expenses"][0]["days"] == 1


def test_a_regular_salaried_worker_has_no_wage_expense(app, client, admin_client):
    """employment_type matters, not just having attendance - a 'regular' salary isn't project-costed by the
    day the way daily wages are."""
    pid = make_project(client, admin_client)
    with app.app_context():
        worker = Worker(name="Sunny Salaried", category="manpower", employment_type="regular", wage_amount=Decimal("30000"))
        db.session.add(worker)
        db.session.flush()
        db.session.add(WorkerAttendance(worker=worker, work_date=date(2026, 10, 1), project_id=pid))
        db.session.commit()
    data = admin_client.get(f"/api/projects/{pid}").get_json()
    assert data["wage_expenses"] == [] and data["total_wage_expense"] == 0


def test_wage_expense_needs_a_wage_amount_set(app, client, admin_client):
    pid = make_project(client, admin_client)
    with app.app_context():
        worker = Worker(name="No Wage Nilesh", category="manpower", employment_type="daily_wages")
        db.session.add(worker)
        db.session.flush()
        db.session.add(WorkerAttendance(worker=worker, work_date=date(2026, 10, 1), project_id=pid))
        db.session.commit()
    data = admin_client.get(f"/api/projects/{pid}").get_json()
    assert data["wage_expenses"] == []


def test_a_day_checked_in_both_ways_is_only_paid_once(app, client, admin_client):
    """A daily-wage worker with a login could in principle show up in both Attendance (their own app
    check-in) and WorkerAttendance (a WhatsApp day logged for them) for the same day and project - see
    _team's own identical dedup reasoning. Must not be paid twice for it."""
    pid = make_project(client, admin_client)
    with app.app_context():
        user = make_user("Deepak Daily")
        worker = daily_wage_worker(user_code=user.code)
        db.session.add(WorkerAttendance(worker=worker, work_date=date(2026, 10, 1), project_id=pid))
        db.session.add(Attendance(user_code=user.code, work_date=date(2026, 10, 1), project_id=pid,
                                   check_in_at=utcnow(), status="approved"))
        db.session.commit()
    data = admin_client.get(f"/api/projects/{pid}").get_json()
    assert data["wage_expenses"][0]["days"] == 1


def test_wage_expense_and_commission_total_stay_separate(app, client, admin_client):
    """The Expense tab shows both (kohal: "it should also have commission part which we implemented
    there") but they're independent figures, not summed into one on the backend."""
    pid = project_with_amount(client, admin_client, 200000)
    with app.app_context():
        cwid = commission_worker()
        worker = daily_wage_worker(wage_amount=Decimal("500"))
        db.session.add(WorkerAttendance(worker=worker, work_date=date(2026, 10, 1), project_id=pid))
        db.session.commit()
    admin_client.post(f"/api/projects/{pid}/expenses", json={"worker_id": cwid, "percent": "5"})
    data = admin_client.get(f"/api/projects/{pid}").get_json()
    assert data["total_wage_expense"] == 500.0
    assert data["total_expense"] == 10000.0


# ---------- Project manager Chandrapur's own project access (kohal, 2026-10-18) ----------
#
# "alocate chadrapur region projects and all other access as project manager to project manager chandrapur
# role" - region-scoped visibility (every project in the Chandrapur district, same as the plain
# project_manager role would see none of), plus every other project_manager power (approving attendance,
# the manager-assignment picker, auto-assigned manager on a project they create).

def chandrapur_pm(app, name="Chetan Chandrapur"):
    """Same module access as the plain project_manager role (attendance + projects, both write) - a custom
    role carries none of its own until the admin sets it up directly in the database (see app/roles.py's own
    docstring), same as kohal did on prod and the emu DB for this one."""
    if db.session.get(Role, COMMISSION_ROLE_KEY) is None:
        db.session.add(Role(key=COMMISSION_ROLE_KEY, name="Project manager Chandrapur", sees_all=False))
        db.session.flush()
        for module_key in ("attendance", "projects"):
            db.session.add(RoleModule(role_key=COMMISSION_ROLE_KEY, module_key=module_key, write_access=True))
        db.session.flush()
    user = make_user(name, role=COMMISSION_ROLE_KEY)
    return signed_in(app, user), user


def test_chandrapur_pm_sees_only_chandrapur_district_projects(app, client, admin_client):
    pid_in = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid_in}", json={"site_district": "Chandrapur"})
    pid_out = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid_out}", json={"site_district": "Nagpur"})

    pm, _ = chandrapur_pm(app)
    ids = [p["id"] for p in pm.get("/api/projects").get_json()["projects"]]
    assert pid_in in ids and pid_out not in ids
    assert pm.get(f"/api/projects/{pid_in}").status_code == 200
    assert pm.get(f"/api/projects/{pid_out}").status_code == 404


def test_chandrapur_pm_also_sees_a_project_they_manage_outside_the_district(app, client, admin_client):
    pid = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid}", json={"site_district": "Nagpur"})
    pm, user = chandrapur_pm(app)
    admin_client.patch(f"/api/projects/{pid}", json={"manager_code": user.code})
    ids = [p["id"] for p in pm.get("/api/projects").get_json()["projects"]]
    assert pid in ids


def test_chandrapur_pm_can_approve_attendance_only_on_projects_they_can_see(app, client, admin_client):
    """Same scoping as visible_projects() itself (kohal, 2026-10-19: "pm chandrapur should only be getting
    material and attendance approvals only for the projects which he has access to") - not every project,
    unlike the plain project_manager role."""
    pid_in = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid_in}", json={"site_district": "Chandrapur"})
    pid_out = make_project(client, admin_client)
    admin_client.patch(f"/api/projects/{pid_out}", json={"site_district": "Nagpur"})
    pm, user = chandrapur_pm(app)
    from app.auth import can_approve_attendance
    with app.app_context():
        in_district = db.session.get(Project, pid_in)
        out_of_district = db.session.get(Project, pid_out)
        assert can_approve_attendance(user, in_district) is True
        assert can_approve_attendance(user, out_of_district) is False


def test_chandrapur_pm_shows_up_in_the_manager_picker(app, client, admin_client):
    pid = make_project(client, admin_client)
    pm, user = chandrapur_pm(app)
    data = admin_client.get(f"/api/projects/{pid}").get_json()
    assert any(m["code"] == user.code for m in data["managers"])


def test_chandrapur_pm_can_be_assigned_as_a_projects_manager(app, client, admin_client):
    pid = make_project(client, admin_client)
    pm, user = chandrapur_pm(app)
    res = admin_client.patch(f"/api/projects/{pid}", json={"manager_code": user.code})
    assert res.status_code == 200 and res.get_json()["project"]["manager_code"] == user.code


def test_a_project_chandrapur_pm_creates_is_auto_assigned_to_them(app):
    pm, user = chandrapur_pm(app)
    res = pm.post("/api/projects", json={"new_client_name": "Auto Assign Test"})
    assert res.status_code == 201 and res.get_json()["project"]["manager_code"] == user.code

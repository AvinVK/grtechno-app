"""Employee management and the Attendance sheet: two admin-only pages over the same worker attendance
data. Grouped by role (the same roles table Users & roles uses), not the old manpower/staff category -
see test_admin_can_still_pick_a_legacy_staff_category_worker_on_a_lead for why category still exists."""

from datetime import date, timedelta

from app.extensions import db
from app.models import Attendance, Client, Project, Worker, WorkerAttendance
from conftest import csrf


def complete_setup(anon, userid, setup_code, pin="482915"):
    """Walk a brand-new user through /set-pin, same as they would on their own phone - only once this
    happens does a matching employee (Worker) get made for them, see app/auth.py sync_worker_for_user."""
    return anon.post("/set-pin", data={
        "csrf": csrf(anon), "userid": userid, "code": setup_code, "pin": pin, "confirm": pin,
    })


def make(name, role=None, category="manpower", present=(), absent=(), first_seen_days_ago=400, project=None):
    """A worker with a present row `present` days ago and an explicit absent row `absent` days ago."""
    today = date.today()
    worker = Worker(name=name, category=category, role_key=role, first_seen=today - timedelta(days=first_seen_days_ago))
    db.session.add(worker)
    db.session.flush()
    for d in present:
        db.session.add(WorkerAttendance(worker=worker, work_date=today - timedelta(days=d), project=project,
                                        check_in_lat=21.1, check_in_lng=79.0))
    for d in absent:
        db.session.add(WorkerAttendance(worker=worker, work_date=today - timedelta(days=d), status="absent"))
    db.session.commit()
    return worker.id


def by_name(rows):
    return {r["name"]: r for r in rows}


# ---------- pages ----------

def test_pages_and_api_are_role_gated(client, manager_client, accounts_client, admin_client, anon):
    """Gated by the "workforce" module - Sales field and Project manager have no access at all; Accountant
    can look (GET) but not touch (kohal's access matrix, 2026-10-14) - used to be admin-only outright,
    before any role had it."""
    for who in (client, manager_client):
        for url in ("/workforce", "/attendance-sheet", "/api/workforce", "/api/workforce/1"):
            assert who.get(url).status_code == 403

    assert accounts_client.get("/workforce").status_code == 200
    assert accounts_client.get("/attendance-sheet").status_code == 200
    assert accounts_client.get("/api/workforce").status_code == 200
    assert accounts_client.get("/api/workforce/1").status_code == 404         # module access granted, no such worker
    assert accounts_client.patch("/api/workforce/1", json={"name": "X"}).status_code == 403   # look, not touch

    assert anon.get("/workforce").status_code == 302 and anon.get("/api/workforce").status_code == 401
    roster = admin_client.get("/workforce").get_data(as_text=True)
    sheet = admin_client.get("/attendance-sheet").get_data(as_text=True)
    assert 'data-mode="roster"' in roster and 'people.js' in roster
    assert 'data-mode="sheet"' in sheet


def test_both_are_in_the_admin_menu_only(client, admin_client):
    for label in ("Employee management", "Attendance sheet"):
        assert label not in client.get("/me").get_data(as_text=True)
        assert label in admin_client.get("/me").get_data(as_text=True)


def test_attendance_is_called_your_attendance_in_the_menu(client):
    assert "Your attendance" in client.get("/me").get_data(as_text=True)


# ---------- grouped by role ----------

def test_people_are_grouped_by_role(admin_client, app):
    with app.app_context():
        make("Sunny Pipe Welder GR", role="welder", present=(0,))
        make("Kuldip Gaurd HR", role="accounts", present=(0,))
        make("Nobody's Assigned Yet")
    body = admin_client.get("/api/workforce").get_json()
    assert [p["name"] for p in body["welder"]] == ["Sunny Pipe Welder GR"]
    assert [p["name"] for p in body["accounts"]] == ["Kuldip Gaurd HR"]
    assert [p["name"] for p in body["unassigned"]] == ["Nobody's Assigned Yet"]
    assert body["roles"]["welder"] == "Welder" and "admin" not in body["roles"]


def test_deployed_is_their_most_recent_present_day(admin_client, app):
    with app.app_context():
        c = Client(name="Kalyani")
        p = Project(client=c, title="Sprinkler install", status="running")
        db.session.add_all([c, p])
        db.session.commit()
        make("On site", role="welder", present=(3,), absent=(0,), project=p)
        make("Never came", role="welder", absent=(1,))
    rows = by_name(admin_client.get("/api/workforce").get_json()["welder"])
    deployed = rows["On site"]["deployed"]
    assert deployed["date"] == (date.today() - timedelta(days=3)).isoformat()      # the absent day after is skipped
    assert deployed["project_title"] == "Sprinkler install" and deployed["map_url"]
    assert rows["Never came"]["deployed"] is None


def test_last_week_dots_never_mark_days_past_the_data_as_absent(admin_client, app):
    with app.app_context():
        make("Sunny", role="welder", present=(2, 4))    # the latest data anyone has is 2 days ago
    week = by_name(admin_client.get("/api/workforce").get_json()["welder"])["Sunny"]["week"]
    # Today first now (kohal, 2026-10-16) - this is the old oldest-to-newest list, reversed.
    assert [d["status"] for d in week] == ["none", "none", "present", "absent", "present", "absent", "absent"]
    assert week[0]["date"] == date.today().isoformat()


def test_sheet_counts_present_days_from_when_they_first_turned_up(admin_client, app):
    with app.app_context():
        make("Old hand", role="welder", present=(0, 1, 2, 3), first_seen_days_ago=400)
        make("New joiner", role="welder", present=(0, 1), first_seen_days_ago=1)
    body = admin_client.get("/api/workforce").get_json()
    rows = by_name(body["welder"])
    assert (rows["Old hand"]["present_days"], rows["Old hand"]["days"]) == (4, 4)       # period is the data's span
    assert (rows["New joiner"]["present_days"], rows["New joiner"]["days"]) == (2, 2)
    assert body["period"] == {"start": (date.today() - timedelta(days=3)).isoformat(), "end": date.today().isoformat()}


# ---------- one person ----------

def test_person_lists_their_days_within_the_period(admin_client, app):
    with app.app_context():
        make("Anchor", present=(0, 5))
        wid = make("Sunny", present=(0, 2), absent=(1,))
    body = admin_client.get(f"/api/workforce/{wid}").get_json()
    assert body["worker"]["name"] == "Sunny"
    assert body["period"]["end"] == date.today().isoformat()
    assert sorted(a["status"] for a in body["attendance"]) == ["absent", "present", "present"]
    assert admin_client.get("/api/workforce/9999").status_code == 404


def test_person_also_lists_their_approved_self_check_in_days(admin_client, anon, app):
    """kohal, 2026-10-16: the same gap as the roster dots (_person_row), now fixed in the person popup/full
    record too - a linked User's own self-check-in only counted here once approved, and a day the WhatsApp
    import already covers isn't duplicated. No WorkerAttendance data anywhere, on purpose - a person with
    only self-check-in data used to get no period at all (_period only ever looked at WorkerAttendance), so
    their own real days never showed here even though the roster's dots already had them."""
    res = admin_client.post("/api/users", json={"name": "Self Checkin Person", "role": "sales_field"})
    body = res.get_json()
    complete_setup(anon, body["user"]["userid"], body["setup_code"])
    with app.app_context():
        from conftest import signed_in
        from app.models import User
        who = signed_in(app, db.session.get(User, body["user"]["code"]))
        wid = db.session.query(Worker.id).filter_by(user_code=body["user"]["code"]).scalar()

    who.post("/api/attendance/check-in", json={"lat": 21.1458, "lng": 79.0882})
    who.post("/api/attendance/check-out")
    detail = admin_client.get(f"/api/workforce/{wid}").get_json()
    assert detail["attendance"] == []          # still pending - not counted yet

    with app.app_context():
        row = Attendance.query.filter_by(user_code=body["user"]["code"]).first()
        row.status = "approved"
        db.session.commit()
    detail = admin_client.get(f"/api/workforce/{wid}").get_json()
    assert len(detail["attendance"]) == 1
    assert detail["attendance"][0]["status"] == "present" and detail["attendance"][0]["work_date"] == date.today().isoformat()


def test_no_data_means_no_period(admin_client, app):
    with app.app_context():
        wid = make("Nobody yet", role="welder")
    body = admin_client.get("/api/workforce").get_json()
    assert body["period"] is None and body["data_until"] is None
    assert body["welder"][0]["days"] == 0 and {d["status"] for d in body["welder"][0]["week"]} == {"none"}
    assert admin_client.get(f"/api/workforce/{wid}").get_json()["period"] is None


# ---------- admin can edit and remove an employee (every employee arrives from Users & roles or the
# WhatsApp import - there's no "add employee" here any more, see app/auth.py sync_worker_for_user) ----------

def test_editing_an_employee_requires_a_name_and_a_valid_role(admin_client, app):
    with app.app_context():
        wid = make("Someone")
    res = admin_client.patch(f"/api/workforce/{wid}", json={"name": ""})
    assert res.status_code == 422 and "name" in res.get_json()["fields"]
    res = admin_client.patch(f"/api/workforce/{wid}", json={"name": "Someone", "role_key": "not-a-role"})
    assert res.status_code == 422 and "role_key" in res.get_json()["fields"]
    res = admin_client.patch(f"/api/workforce/{wid}", json={"name": "Someone", "role_key": "admin"})
    assert res.status_code == 422 and "role_key" in res.get_json()["fields"]


def test_admin_edits_an_employees_name_and_role(admin_client, app):
    with app.app_context():
        wid = make("Typo'd Name", role="welder")
    res = admin_client.patch(f"/api/workforce/{wid}", json={"name": "Fixed Name", "role_key": "fitter"})
    assert res.status_code == 200
    body = res.get_json()["worker"]
    assert body["name"] == "Fixed Name" and body["role_key"] == "fitter"
    listed = admin_client.get("/api/workforce").get_json()
    assert "Fixed Name" in by_name(listed["fitter"])
    assert admin_client.patch("/api/workforce/9999", json={"name": "X"}).status_code == 404


def test_editing_an_employee_can_clear_their_role(admin_client, app):
    with app.app_context():
        wid = make("Was A Welder", role="welder")
    res = admin_client.patch(f"/api/workforce/{wid}", json={"name": "Was A Welder", "role_key": "unassigned"})
    assert res.status_code == 200 and res.get_json()["worker"]["role_key"] is None


def test_only_the_admin_can_edit_or_remove_an_employee(client, manager_client, accounts_client):
    for who in (client, manager_client, accounts_client):
        assert who.patch("/api/workforce/1", json={"name": "X"}).status_code == 403
        assert who.delete("/api/workforce/1").status_code == 403


def test_admin_removes_an_employee_and_their_attendance_goes_with_them(admin_client, app):
    with app.app_context():
        wid = make("Leaving Soon", role="welder", present=(0, 1))
    assert admin_client.delete(f"/api/workforce/{wid}").status_code == 204
    assert admin_client.get(f"/api/workforce/{wid}").status_code == 404
    listed = admin_client.get("/api/workforce").get_json()
    assert "welder" not in listed                                     # the only welder left, so the group is gone too
    assert admin_client.delete("/api/workforce/9999").status_code == 404


def test_removing_an_employee_clears_their_name_from_leads_they_were_picked_on(admin_client, admin, app):
    from app.models import Lead
    with app.app_context():
        wid = make("Picked On A Lead", role="accounts", category="staff")
        lead = Lead(company="Some Co", contact_name="X", phone="9800000000", enquired_by_id=wid, owner_code=admin.code)
        db.session.add(lead)
        db.session.commit()
        lead_id = lead.id

    assert admin_client.delete(f"/api/workforce/{wid}").status_code == 204
    with app.app_context():
        kept = db.session.get(Lead, lead_id)
        assert kept is not None and kept.enquired_by_id is None


def test_editing_an_employee_never_touches_the_legacy_category(admin_client, app):
    """category still decides who Leads offers as a surveyor/enquired-by (app/api.py) - unrelated to
    role_key, so Employee management must leave it at its default, not silently change who can be picked
    there."""
    with app.app_context():
        wid = make("New Hire", role="welder")
    admin_client.patch(f"/api/workforce/{wid}", json={"name": "New Hire", "role_key": "fitter"})
    with app.app_context():
        assert db.session.get(Worker, wid).category == "manpower"


# ---------- HR details and the salary/wages log ----------

def test_editing_an_employee_captures_full_hr_details(admin_client, app):
    with app.app_context():
        wid = make("Full Details", role="fitter")
    res = admin_client.patch(f"/api/workforce/{wid}", json={
        "name": "Full Details", "role_key": "fitter", "age": 29, "qualification": "ITI Fitter",
        "experience": "6 years in sprinkler installation", "skills": "Welding, pipe fitting",
        "phone": "9876543210", "joining_date": "2026-01-15", "employment_type": "regular",
        "wage_amount": 22000, "pf_number": "PF1234567", "esic_number": "ESIC7654321",
        "reference": "Referred by Ramesh",
    })
    assert res.status_code == 200
    body = res.get_json()["worker"]
    assert body["age"] == 29 and body["qualification"] == "ITI Fitter"
    assert body["experience"] == "6 years in sprinkler installation"
    assert body["skills"] == "Welding, pipe fitting" and body["phone"] == "9876543210"
    assert body["joining_date"] == "2026-01-15" and body["employment_type"] == "regular"
    assert body["wage_amount"] == 22000.0
    assert body["pf_number"] == "PF1234567" and body["esic_number"] == "ESIC7654321"
    assert body["reference"] == "Referred by Ramesh"


def test_employment_type_must_be_regular_or_daily_wages(admin_client, app):
    with app.app_context():
        wid = make("X")
    res = admin_client.patch(f"/api/workforce/{wid}", json={"name": "X", "employment_type": "contractor"})
    assert res.status_code == 422 and "employment_type" in res.get_json()["fields"]


def test_age_must_be_a_plausible_number(admin_client, app):
    with app.app_context():
        wid = make("X")
    res = admin_client.patch(f"/api/workforce/{wid}", json={"name": "X", "age": 5})
    assert res.status_code == 422 and "age" in res.get_json()["fields"]


def test_editing_an_employee_updates_their_hr_details(admin_client, app):
    with app.app_context():
        wid = make("Needs Details")
    res = admin_client.patch(f"/api/workforce/{wid}", json={
        "name": "Needs Details", "age": 34, "wage_amount": 500, "employment_type": "daily_wages",
    })
    assert res.status_code == 200
    body = res.get_json()["worker"]
    assert body["age"] == 34 and body["wage_amount"] == 500.0 and body["employment_type"] == "daily_wages"


def test_employee_detail_includes_payments_and_attendance(admin_client, app):
    with app.app_context():
        wid = make("Has Payments", present=(0,))
    res = admin_client.patch(f"/api/workforce/{wid}", json={"name": "Has Payments", "payments": [
        {"label": "October salary", "amount": 20000, "mode": "Bank transfer", "paid_date": "2026-10-05"},
        {"label": "November salary", "amount": 20000},
    ]})
    assert res.status_code == 200
    body = res.get_json()["worker"]
    assert [p["label"] for p in body["payments"]] == ["October salary", "November salary"]
    assert body["paid_amount"] == 20000.0            # only the one with a paid_date counts

    detail = admin_client.get(f"/api/workforce/{wid}").get_json()
    assert detail["worker"]["paid_amount"] == 20000.0
    assert len(detail["worker"]["payments"]) == 2
    assert detail["payment_modes"]


def test_payments_must_have_a_label_and_a_valid_amount(admin_client, app):
    with app.app_context():
        wid = make("Bad Payment")
    res = admin_client.patch(f"/api/workforce/{wid}", json={"payments": [{"label": "", "amount": 100}]})
    assert res.status_code == 422 and "payments" in res.get_json()["fields"]
    res = admin_client.patch(f"/api/workforce/{wid}", json={"payments": [{"label": "X", "amount": -5}]})
    assert res.status_code == 422 and "payments" in res.get_json()["fields"]


def test_editing_payments_replaces_the_whole_log(admin_client, app):
    with app.app_context():
        wid = make("Replace Log")
    admin_client.patch(f"/api/workforce/{wid}", json={"payments": [{"label": "A", "amount": 100}, {"label": "B", "amount": 200}]})
    res = admin_client.patch(f"/api/workforce/{wid}", json={"payments": [{"label": "Only one now", "amount": 300}]})
    body = res.get_json()["worker"]
    assert len(body["payments"]) == 1 and body["payments"][0]["label"] == "Only one now"


def test_removing_an_employee_removes_their_payment_log_too(admin_client, app):
    with app.app_context():
        wid = make("Leaving With Payments")
    admin_client.patch(f"/api/workforce/{wid}", json={"payments": [{"label": "A", "amount": 100}]})
    assert admin_client.delete(f"/api/workforce/{wid}").status_code == 204
    with app.app_context():
        from app.models import WorkerPayment
        assert WorkerPayment.query.filter_by(worker_id=wid).count() == 0


# ---------- "needs details" - someone who arrived via Users & roles, not filled in yet ----------

def test_a_user_added_via_users_and_roles_is_flagged_as_needing_details(admin_client, anon):
    res = admin_client.post("/api/users", json={"name": "Priya Enquiry", "role": "sales_office"})
    body = res.get_json()
    complete_setup(anon, body["user"]["userid"], body["setup_code"])
    rows = by_name(admin_client.get("/api/workforce").get_json()["sales_office"])
    assert rows["Priya Enquiry"]["needs_details"] is True


def test_a_still_pending_user_does_not_show_up_in_employee_management_at_all(admin_client):
    admin_client.post("/api/users", json={"name": "Not Yet Signed In", "role": "sales_office"})
    rows = by_name(admin_client.get("/api/workforce").get_json().get("sales_office", []))
    assert "Not Yet Signed In" not in rows


def test_filling_in_a_phone_clears_the_flag(admin_client, anon, app):
    res = admin_client.post("/api/users", json={"name": "Rohit Field", "role": "sales_field"})
    body = res.get_json()
    complete_setup(anon, body["user"]["userid"], body["setup_code"])
    with app.app_context():
        worker_id = Worker.query.filter_by(user_code=body["user"]["code"]).first().id
    admin_client.patch(f"/api/workforce/{worker_id}", json={"name": "Rohit Field", "phone": "9876500000"})
    rows = by_name(admin_client.get("/api/workforce").get_json()["sales_field"])
    assert rows["Rohit Field"]["needs_details"] is False


def test_a_whatsapp_imported_worker_is_never_flagged(admin_client, app):
    with app.app_context():
        make("From WhatsApp", role="welder")
    rows = by_name(admin_client.get("/api/workforce").get_json()["welder"])
    assert rows["From WhatsApp"]["needs_details"] is False


# ---------- "live" - a linked User currently checked in (app/attendance.py) ----------

def test_a_linked_user_with_an_open_session_shows_as_live_today(admin_client, anon, app):
    from conftest import signed_in
    from app.models import User

    res = admin_client.post("/api/users", json={"name": "Live Checkin Test", "role": "sales_field"})
    body = res.get_json()
    complete_setup(anon, body["user"]["userid"], body["setup_code"])
    with app.app_context():
        who = signed_in(app, db.session.get(User, body["user"]["code"]))

    rows = by_name(admin_client.get("/api/workforce").get_json()["sales_field"])
    assert rows["Live Checkin Test"]["week"][0]["status"] != "live"      # not checked in yet; today is first (kohal, 2026-10-16)

    assert who.post("/api/attendance/check-in", json={"lat": 21.1458, "lng": 79.0882}).status_code == 201
    rows = by_name(admin_client.get("/api/workforce").get_json()["sales_field"])
    assert rows["Live Checkin Test"]["week"][0]["status"] == "live"

    who.post("/api/attendance/check-out")
    rows = by_name(admin_client.get("/api/workforce").get_json()["sales_field"])
    assert rows["Live Checkin Test"]["week"][0]["status"] != "live"      # checked out - no longer live


def test_an_approved_self_check_in_also_counts_as_a_present_day(admin_client, anon, app):
    """kohal, 2026-10-16: the roster's dots only ever looked at the older WhatsApp-import attendance - a
    linked User's own self-check-in (app/attendance.py) didn't count at all, so a real day's work there
    showed no dot. Now it does, once approved (a pending one still doesn't - same rule as everywhere else)."""
    res = admin_client.post("/api/users", json={"name": "Self Checkin Test", "role": "sales_field"})
    body = res.get_json()
    complete_setup(anon, body["user"]["userid"], body["setup_code"])
    with app.app_context():
        from conftest import signed_in
        from app.models import User
        who = signed_in(app, db.session.get(User, body["user"]["code"]))

    who.post("/api/attendance/check-in", json={"lat": 21.1458, "lng": 79.0882})
    who.post("/api/attendance/check-out")
    rows = by_name(admin_client.get("/api/workforce").get_json()["sales_field"])
    assert rows["Self Checkin Test"]["week"][0]["status"] == "none"      # pending - not counted yet

    with app.app_context():
        row = Attendance.query.filter_by(user_code=body["user"]["code"]).first()
        row.status = "approved"
        db.session.commit()
    rows = by_name(admin_client.get("/api/workforce").get_json()["sales_field"])
    assert rows["Self Checkin Test"]["week"][0]["status"] == "present"

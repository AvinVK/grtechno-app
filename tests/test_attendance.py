from datetime import date, datetime, timedelta

from app.extensions import db
from app.models import AbsenceRequest, Attendance, Client, Project, Worker, utcnow

from conftest import make_user, signed_in

LOC = {"lat": 21.1458, "lng": 79.0882}          # Nagpur, used wherever a test just needs some valid location


def check_in(client, **extra):
    return client.post("/api/attendance/check-in", json={**LOC, **extra})


def make_project(title="Sprinkler install"):
    client = Client(name="Sunrise Hospital")
    db.session.add(client)
    db.session.flush()
    project = Project(client=client, title=title, status="running")
    db.session.add(project)
    db.session.commit()
    return project


def daily_wage_user(app, name="Deepak Daily", pin="285193"):
    """A signed-in User with a matching daily-wage Worker (see auth._is_daily_wage) - only this employment
    type is held to the shift rules below (kohal, 2026-10-19)."""
    user = make_user(name, pin=pin)
    worker = Worker(name=name, category="manpower", employment_type="daily_wages", user_code=user.code)
    db.session.add(worker)
    db.session.commit()
    return signed_in(app, user), user


# ---------- everyone can open it ----------

def test_every_role_can_open_attendance(client, manager_client, accounts_client, admin_client):
    for who in (client, manager_client, accounts_client, admin_client):
        assert who.get("/attendance").status_code == 200
        assert who.get("/api/attendance/state").status_code == 200


def test_needs_sign_in(anon):
    assert anon.get("/api/attendance/state").status_code == 401
    assert anon.get("/attendance").status_code == 302


def test_the_sheet_link_only_shows_up_for_someone_who_can_also_see_it(manager_client, accounts_client, admin_client):
    """A "Sheet" link to the Attendance sheet (app/workers.py) only makes sense for someone who can also
    open it - the project manager has Attendance but not workforce, so data-can-see-workforce stays 0 for
    them (kohal, 2026-10-20: wanted the two attendance views reachable from each other)."""
    assert 'data-can-see-workforce="0"' in manager_client.get("/attendance").get_data(as_text=True)
    assert 'data-can-see-workforce="1"' in accounts_client.get("/attendance").get_data(as_text=True)
    assert 'data-can-see-workforce="1"' in admin_client.get("/attendance").get_data(as_text=True)


# ---------- checking in and out ----------

def test_check_in_with_no_project_then_check_out(client):
    state = client.get("/api/attendance/state").get_json()
    assert state["today"] is None and state["can_see_team"] is False

    res = check_in(client)
    assert res.status_code == 201
    today = res.get_json()["today"]
    assert today["project_id"] is None and today["check_out_at"] is None and today["hours"] is None
    assert today["check_in_lat"] == LOC["lat"] and today["check_in_map_url"]

    out = client.post("/api/attendance/check-out")
    assert out.status_code == 200
    assert out.get_json()["today"]["check_out_at"] is not None
    assert out.get_json()["today"]["hours"] is not None


def test_check_in_against_a_project(client, app):
    with app.app_context():
        project = make_project()
        project_id = project.id
    res = check_in(client, project_id=project_id)
    body = res.get_json()["today"]
    assert body["project_id"] == project_id and body["project_title"] == "Sprinkler install"


def test_check_in_with_a_bad_project_id_is_rejected(client):
    res = check_in(client, project_id=999999)
    assert res.status_code == 422 and "project_id" in res.get_json()["fields"]


# ---------- a location is required ----------

def test_check_in_can_carry_a_location(client):
    res = check_in(client)
    assert res.status_code == 201
    today = res.get_json()["today"]
    assert today["check_in_lat"] == 21.1458 and today["check_in_lng"] == 79.0882
    assert today["check_in_map_url"] == "https://maps.google.com/?q=21.1458,79.0882"


def test_check_in_needs_a_location(client):
    """Checking in with no location at all - the phone had no GPS, or the person never agreed to share it -
    is refused, not silently allowed. This is enforced here, not only by the screen's own prompt, so it
    cannot be skipped by calling the API directly."""
    res = client.post("/api/attendance/check-in", json={})
    assert res.status_code == 422 and "lat" in res.get_json()["fields"]
    assert client.get("/api/attendance/state").get_json()["today"] is None    # nothing was recorded


def test_check_in_needs_both_coordinates(client):
    res = client.post("/api/attendance/check-in", json={"lat": 21.1458})
    assert res.status_code == 422 and "lat" in res.get_json()["fields"]


def test_a_bad_location_is_rejected(client):
    res = check_in(client, lat=200)
    assert res.status_code == 422 and "lat" in res.get_json()["fields"]


def test_state_reports_whether_a_location_is_required(client):
    assert client.get("/api/attendance/state").get_json()["location_required"] is True


def test_location_can_be_switched_off_for_local_dev_only(app, client):
    """REQUIRE_ATTENDANCE_LOCATION=0 - a local .env only, never prod (kohal, 2026-10-16: "just in dev") -
    see app/config.py. Never read from an actual .env in tests; set directly on the app's own config."""
    with app.app_context():
        app.config["REQUIRE_ATTENDANCE_LOCATION"] = False
        try:
            assert client.get("/api/attendance/state").get_json()["location_required"] is False
            res = client.post("/api/attendance/check-in", json={})
            assert res.status_code == 201
            assert res.get_json()["today"]["check_in_lat"] is None
        finally:
            app.config["REQUIRE_ATTENDANCE_LOCATION"] = True


def test_team_register_also_carries_the_location(client, admin_client):
    check_in(client)
    record = admin_client.get("/api/attendance/team").get_json()["records"][0]
    assert record["check_in_map_url"] == "https://maps.google.com/?q=21.1458,79.0882"


def test_cannot_check_in_again_while_already_checked_in(client):
    assert check_in(client).status_code == 201
    again = check_in(client)
    assert again.status_code == 409


def test_can_check_in_again_after_checking_out(client):
    """A lunch break, a second site - checking in and out more than once in the same day makes a second
    row for that day, not an error."""
    first = check_in(client).get_json()["today"]["id"]
    client.post("/api/attendance/check-out")
    second = check_in(client)
    assert second.status_code == 201
    assert second.get_json()["today"]["id"] != first

    state = client.get("/api/attendance/state").get_json()
    assert len(state["today_sessions"]) == 2
    assert state["today_sessions"][0]["id"] == first and state["today_sessions"][0]["check_out_at"] is not None
    assert state["today_sessions"][1]["id"] == second.get_json()["today"]["id"]
    assert state["today"]["id"] == second.get_json()["today"]["id"]      # the open one


def test_history_groups_more_than_one_session_a_day(client):
    check_in(client)
    client.post("/api/attendance/check-out")
    check_in(client)
    client.post("/api/attendance/check-out")
    state = client.get("/api/attendance/state").get_json()
    todays = [h for h in state["history"] if h["work_date"] == date.today().isoformat()]
    assert len(todays) == 2


def test_cannot_check_out_without_checking_in(client):
    assert client.post("/api/attendance/check-out").status_code == 409


def test_cannot_check_out_twice(client):
    check_in(client)
    assert client.post("/api/attendance/check-out").status_code == 200
    assert client.post("/api/attendance/check-out").status_code == 409


def test_an_open_session_left_over_from_an_earlier_day_still_blocks_a_new_check_in(client, app, user):
    """A forgotten check-out on, say, Wednesday must not let Thursday's check-in through anyway - it has to
    be checked out first, same as a same-day open session (kohal, 2026-10-15, screenshot: Wed left "still
    checked in", Thu allowed to check in regardless)."""
    with app.app_context():
        db.session.add(Attendance(
            user_code=user.code, work_date=date.today() - timedelta(days=1), check_in_at=utcnow(),
        ))
        db.session.commit()
    res = check_in(client)
    assert res.status_code == 409

    state = client.get("/api/attendance/state").get_json()
    assert state["today"] is not None       # the old open session, surfaced so Check out still works
    assert state["today"]["work_date"] == (date.today() - timedelta(days=1)).isoformat()

    out = client.post("/api/attendance/check-out")
    assert out.status_code == 200
    assert check_in(client).status_code == 201     # now that it's closed, a fresh check-in works


def test_history_shows_past_days(client, app, user):
    with app.app_context():
        db.session.add(Attendance(
            user_code=user.code, work_date=date.today() - timedelta(days=1), check_in_at=utcnow(),
        ))
        db.session.commit()
    state = client.get("/api/attendance/state").get_json()
    assert len(state["history"]) == 1
    assert state["history"][0]["work_date"] == (date.today() - timedelta(days=1)).isoformat()


# ---------- who sees whose attendance ----------

def test_only_sees_all_roles_can_open_the_team_register(client, accounts_client, admin_client):
    check_in(client)
    assert client.get("/api/attendance/team").status_code == 403
    assert accounts_client.get("/api/attendance/team").status_code == 200
    assert admin_client.get("/api/attendance/team").status_code == 200


def test_team_register_shows_everyones_checkins_for_the_day(client, manager_client, admin_client):
    check_in(client)
    check_in(manager_client)
    body = admin_client.get("/api/attendance/team").get_json()
    names = {r["user_name"] for r in body["records"]}
    assert {"Tester", "Priya Manager"} <= names


def test_team_register_can_be_filtered_by_date(client, admin_client):
    check_in(client)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    empty = admin_client.get(f"/api/attendance/team?date={yesterday}").get_json()
    assert empty["records"] == []
    today = admin_client.get(f"/api/attendance/team?date={date.today().isoformat()}").get_json()
    assert len(today["records"]) == 1


def test_a_users_state_only_shows_their_own_history(client, manager_client):
    check_in(client)
    check_in(manager_client)
    state = client.get("/api/attendance/state").get_json()
    assert state["today"]["user_code"] not in (None,)  # sanity: a record is theirs
    assert all(h["user_name"] == "Tester" for h in state["history"])


# ---------- deleting a record ----------

def test_only_sees_all_roles_can_delete_a_record(client, manager_client, admin_client):
    record_id = check_in(client).get_json()["today"]["id"]
    assert client.delete(f"/api/attendance/{record_id}").status_code == 403
    assert manager_client.delete(f"/api/attendance/{record_id}").status_code == 403
    assert admin_client.delete(f"/api/attendance/{record_id}").status_code == 204
    assert client.get("/api/attendance/state").get_json()["today"] is None


def test_deleting_an_unknown_record_is_a_404(admin_client):
    assert admin_client.delete("/api/attendance/999999").status_code == 404



# ---------- the admin doesn't check in ----------

def test_the_admin_cannot_check_in_or_out(admin_client):
    assert admin_client.post("/api/attendance/check-in", json={"lat": 21.1, "lng": 79.0}).status_code == 403
    assert admin_client.post("/api/attendance/check-out").status_code == 403


def test_the_admins_attendance_page_is_the_team_register(admin_client, client):
    html = admin_client.get("/attendance").get_data(as_text=True)
    assert 'data-team-only="1"' in html
    assert 'data-team-only="0"' in client.get("/attendance").get_data(as_text=True)



# ---------- what they're working on: a project, office work or marketing work ----------

def test_check_in_to_marketing_work(client):
    res = client.post("/api/attendance/check-in", json={"work": "marketing", "lat": 21.1, "lng": 79.0})
    assert res.status_code == 201
    today = res.get_json()["today"]
    assert today["project_id"] is None and today["work_kind"] == "marketing" and today["work_label"] == "Marketing work"


def test_office_work_is_the_default_without_a_project(client):
    today = client.post("/api/attendance/check-in", json={"lat": 21.1, "lng": 79.0}).get_json()["today"]
    assert today["work_kind"] == "" and today["work_label"] == "Office work"


def test_an_unknown_kind_of_work_is_refused(client):
    res = client.post("/api/attendance/check-in", json={"work": "napping", "lat": 21.1, "lng": 79.0})
    assert res.status_code == 422 and "work" in res.get_json()["fields"]


# ---------- approval (kohal, 2026-10-16: "Attendance should be approved by project manager or site
# supervisor who is checked in on tha project") ----------

def test_office_work_needs_admin_or_company_director_to_approve(client):
    today = check_in(client).get_json()["today"]
    assert today["status"] == "pending" and today["approved_by_name"] is None


def test_check_in_by_the_admin_is_impossible_so_company_director_is_the_fallback(app):
    director = signed_in(app, make_user("Dilip Director", role="company_director"))
    today = director.post("/api/attendance/check-in", json=LOC).get_json()["today"]
    assert today["status"] == "approved" and today["approved_by_name"] == "Dilip Director"


def test_check_in_against_a_project_by_someone_unconnected_to_it_is_pending(app, client):
    with app.app_context():
        project = make_project()
        pid = project.id
    today = check_in(client, project_id=pid).get_json()["today"]
    assert today["status"] == "pending"


def test_check_in_by_the_projects_own_manager_is_approved_immediately(app):
    with app.app_context():
        pid = make_project().id
    manager = make_user("Priya Manager", role="project_manager")
    pm_client = signed_in(app, manager)
    today = pm_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid}).get_json()["today"]
    assert today["status"] == "approved" and today["approved_by_name"] == "Priya Manager"


def test_a_site_supervisors_own_check_in_still_waits_for_approval(app):
    """They can't be "the currently checked-in supervisor" approving themselves - only the project manager,
    admin or Company Director can sign off their own attendance there."""
    with app.app_context():
        pid = make_project().id
    supervisor = make_user("Site Sam", role="supervisor")
    sup_client = signed_in(app, supervisor)
    today = sup_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid}).get_json()["today"]
    assert today["status"] == "pending"


def contractor_fapa_user(app, name="Chandan Contractor"):
    """Contractor FAPA (kohal, 2026-10-19: "he needs to be given site supervisor access") - a custom role
    with the same module access as Site supervisor, set up directly in the database same as on prod."""
    from app.models import Role, RoleModule
    if db.session.get(Role, "contractor_fapa") is None:
        db.session.add(Role(key="contractor_fapa", name="Contractor FAPA", sees_all=False))
        db.session.flush()
        for module_key in ("projects", "attendance"):
            db.session.add(RoleModule(role_key="contractor_fapa", module_key=module_key, write_access=True))
        db.session.flush()
    user = make_user(name, role="contractor_fapa")
    return signed_in(app, user), user


def test_contractor_fapa_approves_attendance_like_a_site_supervisor(app, client):
    """Full parity with Site supervisor, not just module access - SITE_SUPERVISOR_ROLE_KEYS is what actually
    grants the "currently checked in there" approval power (see auth.can_approve_attendance)."""
    with app.app_context():
        pid = make_project().id
    contractor_client, contractor = contractor_fapa_user(app)
    record_id = check_in(client, project_id=pid).get_json()["today"]["id"]
    assert contractor_client.post(f"/api/attendance/{record_id}/approve").status_code == 403   # not checked in there yet

    contractor_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid})
    assert contractor_client.post(f"/api/attendance/{record_id}/approve").status_code == 200


def test_approving_an_attendance_record(app, client):
    with app.app_context():
        pid = make_project().id
    today = check_in(client, project_id=pid).get_json()["today"]
    record_id = today["id"]

    manager = make_user("Priya Manager", role="project_manager")
    pm_client = signed_in(app, manager)
    res = pm_client.post(f"/api/attendance/{record_id}/approve")
    assert res.status_code == 200
    assert res.get_json()["record"]["status"] == "approved" and res.get_json()["record"]["approved_by_name"] == "Priya Manager"


def test_only_an_eligible_person_can_approve_or_reject(app, client):
    with app.app_context():
        pid = make_project().id
    record_id = check_in(client, project_id=pid).get_json()["today"]["id"]
    other = signed_in(app, make_user("Someone Else"))
    assert other.post(f"/api/attendance/{record_id}/approve").status_code == 403
    assert other.post(f"/api/attendance/{record_id}/reject").status_code == 403


def test_cannot_approve_or_reject_twice(app, client):
    with app.app_context():
        pid = make_project().id
    record_id = check_in(client, project_id=pid).get_json()["today"]["id"]
    manager = signed_in(app, make_user("Priya Manager", role="project_manager"))
    assert manager.post(f"/api/attendance/{record_id}/approve").status_code == 200
    assert manager.post(f"/api/attendance/{record_id}/approve").status_code == 409
    assert manager.post(f"/api/attendance/{record_id}/reject").status_code == 409


# ---------- the rejection popup (kohal, 2026-10-20: "a popup as soon as attendance was rejected so that
# user knows" - before this, a rejected session just sat as a chip further down their own history, with
# nothing actively telling them) ----------

def test_a_rejected_record_shows_up_for_the_person_it_belongs_to(app, client):
    with app.app_context():
        pid = make_project().id
    record_id = check_in(client, project_id=pid).get_json()["today"]["id"]
    manager = signed_in(app, make_user("Priya Manager", role="project_manager"))
    manager.post(f"/api/attendance/{record_id}/reject")

    res = client.get("/api/attendance/rejections")
    assert res.status_code == 200
    rows = res.get_json()["rejections"]
    assert len(rows) == 1 and rows[0]["id"] == record_id and rows[0]["status"] == "rejected"


def test_an_approved_record_never_shows_up_as_a_rejection(app, client):
    with app.app_context():
        pid = make_project().id
    record_id = check_in(client, project_id=pid).get_json()["today"]["id"]
    manager = signed_in(app, make_user("Priya Manager", role="project_manager"))
    manager.post(f"/api/attendance/{record_id}/approve")
    assert client.get("/api/attendance/rejections").get_json()["rejections"] == []


def test_dismissing_a_rejection_removes_it_from_the_list(app, client):
    with app.app_context():
        pid = make_project().id
    record_id = check_in(client, project_id=pid).get_json()["today"]["id"]
    manager = signed_in(app, make_user("Priya Manager", role="project_manager"))
    manager.post(f"/api/attendance/{record_id}/reject")

    assert client.post(f"/api/attendance/{record_id}/dismiss-rejection").status_code == 204
    assert client.get("/api/attendance/rejections").get_json()["rejections"] == []


def test_only_the_person_it_belongs_to_can_dismiss_it(app, client):
    with app.app_context():
        pid = make_project().id
    record_id = check_in(client, project_id=pid).get_json()["today"]["id"]
    manager = signed_in(app, make_user("Priya Manager", role="project_manager"))
    manager.post(f"/api/attendance/{record_id}/reject")

    other = signed_in(app, make_user("Someone Else"))
    assert other.post(f"/api/attendance/{record_id}/dismiss-rejection").status_code == 404
    # Still there for the person it actually belongs to - someone else's attempt didn't quietly dismiss it.
    assert len(client.get("/api/attendance/rejections").get_json()["rejections"]) == 1


def test_dismissing_an_unknown_record_is_a_404(client):
    assert client.post("/api/attendance/999999/dismiss-rejection").status_code == 404


def test_checking_in_or_out_never_needs_approval_first(client):
    """The check-in/check-out action itself is never blocked by approval - only counts/reports are (see
    the next tests) - otherwise someone could get stuck unable to check out until somebody approves."""
    assert check_in(client).status_code == 201
    assert client.post("/api/attendance/check-out").status_code == 200
    assert check_in(client).status_code == 201     # checking in again still works, still just goes pending


def test_a_pending_day_is_excluded_from_the_weekly_count(app, client, user):
    check_in(client)
    client.post("/api/attendance/check-out")
    assert client.get("/api/me").get_json()                      # sanity: still signed in
    html = client.get("/me").get_data(as_text=True)
    assert "0 days this week" in html                             # pending, so it doesn't count yet

    with app.app_context():
        row = Attendance.query.filter_by(user_code=user.code).first()
        row.status = "approved"
        db.session.commit()
    html = client.get("/me").get_data(as_text=True)
    assert "1 day this week" in html


# ---------- a daily-wage worker's shift rules (kohal, 2026-10-19: "checkedin after this [7-7.30] then only
# Admin can approve", "checkout after 7.00 pm", "Multiple check in and check out approved by project
# manager only") - nobody else's attendance is held to these; see auth.attendance_restriction. ----------

def test_a_salaried_workers_late_checkin_is_unaffected(app):
    """The whole point of scoping this to daily wages (kohal: confirmed "Daily-wage workers only") - a
    regular/contractor check-in at any hour follows the ordinary rule, same as before this existed."""
    with app.app_context():
        pid = make_project().id
    manager = make_user("Priya Manager", role="project_manager")
    worker_user = make_user("Office Omkar")
    worker_client = signed_in(app, worker_user)
    record_id = worker_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid}).get_json()["today"]["id"]
    with app.app_context():
        row = db.session.get(Attendance, record_id)
        row.check_in_at = datetime(2026, 10, 19, 4, 0)       # 4:00 UTC = 9:30am IST - "late" if it mattered
        db.session.commit()
    pm_client = signed_in(app, manager)
    assert pm_client.post(f"/api/attendance/{record_id}/approve").status_code == 200


def test_a_late_daily_wage_checkin_can_only_be_approved_by_the_admin(app, admin_client):
    with app.app_context():
        pid = make_project().id
    worker_client, worker_user = daily_wage_user(app)
    record_id = worker_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid}).get_json()["today"]["id"]
    with app.app_context():
        row = db.session.get(Attendance, record_id)
        row.check_in_at = datetime(2026, 10, 19, 3, 0)       # 3:00 UTC = 8:30am IST - after the 7:30 cutoff
        db.session.commit()

    manager = make_user("Priya Manager", role="project_manager")
    pm_client = signed_in(app, manager)
    director = signed_in(app, make_user("Dilip Director", role="company_director"))
    assert pm_client.post(f"/api/attendance/{record_id}/approve").status_code == 403
    assert director.post(f"/api/attendance/{record_id}/approve").status_code == 403    # admin-only, not even Company Director

    res = admin_client.post(f"/api/attendance/{record_id}/approve")
    assert res.status_code == 200 and res.get_json()["record"]["status"] == "approved"


def test_an_on_time_daily_wage_checkin_follows_the_normal_rule(app):
    """7:00-7:30am is on time - the project's own manager can approve it immediately, same as anyone else's
    on-time check-in against their project."""
    with app.app_context():
        pid = make_project().id
    manager = make_user("Priya Manager", role="project_manager")
    pm_client = signed_in(app, manager)
    worker_client, worker_user = daily_wage_user(app)
    record_id = worker_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid}).get_json()["today"]["id"]
    with app.app_context():
        row = db.session.get(Attendance, record_id)
        row.check_in_at = datetime(2026, 10, 19, 1, 45)      # 1:45 UTC = 7:15am IST
        db.session.commit()
    assert pm_client.post(f"/api/attendance/{record_id}/approve").status_code == 200


def _check_in_at_a_safe_on_time_hour(record_id):
    """Pins a session's check_in_at to 7:15am IST - on time regardless of whatever the real clock reads
    when the test happens to run - so only the thing each test actually varies (the checkout time, or a
    second session's project) decides the outcome."""
    row = db.session.get(Attendance, record_id)
    row.check_in_at = datetime(2026, 10, 19, 1, 45)
    db.session.commit()


def test_an_early_checkout_sends_an_already_approved_session_back_to_pending(app, monkeypatch):
    with app.app_context():
        pid = make_project().id
    manager = make_user("Priya Manager", role="project_manager")
    pm_client = signed_in(app, manager)
    worker_client, worker_user = daily_wage_user(app)
    record_id = worker_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid}).get_json()["today"]["id"]
    with app.app_context():
        _check_in_at_a_safe_on_time_hour(record_id)
    assert pm_client.post(f"/api/attendance/{record_id}/approve").status_code == 200

    # Stamp the checkout itself at 5:30pm IST (12:00 UTC) - before the 7pm cutoff - instead of relying on
    # whatever the real clock happens to read when this test runs.
    monkeypatch.setattr("app.attendance.utcnow", lambda: datetime(2026, 10, 19, 12, 0))
    out = worker_client.post("/api/attendance/check-out").get_json()["today"]
    assert out["status"] == "pending" and out["approved_by_name"] is None

    res = pm_client.get("/api/attendance/approvals").get_json()
    assert any(r["id"] == record_id and r["status"] == "pending" for r in res["approvals"])


def test_a_checkout_at_or_after_7pm_does_not_revert_an_approved_session(app, monkeypatch):
    with app.app_context():
        pid = make_project().id
    manager = make_user("Priya Manager", role="project_manager")
    pm_client = signed_in(app, manager)
    worker_client, worker_user = daily_wage_user(app)
    record_id = worker_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid}).get_json()["today"]["id"]
    with app.app_context():
        _check_in_at_a_safe_on_time_hour(record_id)
    assert pm_client.post(f"/api/attendance/{record_id}/approve").status_code == 200

    monkeypatch.setattr("app.attendance.utcnow", lambda: datetime(2026, 10, 19, 13, 31))   # 7:01pm IST
    out = worker_client.post("/api/attendance/check-out").get_json()["today"]
    assert out["status"] == "approved" and out["approved_by_name"] == "Priya Manager"


def test_a_second_session_against_a_different_project_needs_a_project_manager_not_a_site_supervisor(app, monkeypatch):
    with app.app_context():
        pid_a = make_project("Site A").id
        pid_b = make_project("Site B").id
    manager = make_user("Priya Manager", role="project_manager")
    pm_client = signed_in(app, manager)
    supervisor = make_user("Site Sam", role="supervisor")
    sup_client = signed_in(app, supervisor)
    worker_client, worker_user = daily_wage_user(app)

    # Both sessions pinned to a safely on-time hour - only which project they're against is what this test
    # varies; otherwise whichever real hour happens to be on the clock when this test runs could make the
    # first session "late" instead (admin-only) and break the asserts below for an unrelated reason.
    monkeypatch.setattr("app.attendance.utcnow", lambda: datetime(2026, 10, 19, 1, 45))    # 7:15am IST
    first = worker_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid_a}).get_json()["today"]
    assert pm_client.post(f"/api/attendance/{first['id']}/approve").status_code == 200
    worker_client.post("/api/attendance/check-out")

    monkeypatch.setattr("app.attendance.utcnow", lambda: datetime(2026, 10, 19, 1, 50))    # 7:20am IST
    second = worker_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid_b}).get_json()["today"]
    assert second["status"] == "pending"

    # The site supervisor is currently checked in on project B themselves - normally enough to approve an
    # on-time session there - but this one is the worker's 2nd+ session against a different project than
    # their first that day, so it's narrowed to a project manager (or admin) only.
    sup_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid_b})
    assert sup_client.post(f"/api/attendance/{second['id']}/approve").status_code == 403
    assert pm_client.post(f"/api/attendance/{second['id']}/approve").status_code == 200


def test_a_second_session_against_the_same_project_follows_the_normal_rule(app, monkeypatch):
    """Only a *different* project triggers the narrower rule - lunch and back to the same site doesn't."""
    with app.app_context():
        pid = make_project().id
    manager = make_user("Priya Manager", role="project_manager")
    pm_client = signed_in(app, manager)
    worker_client, worker_user = daily_wage_user(app)

    monkeypatch.setattr("app.attendance.utcnow", lambda: datetime(2026, 10, 19, 1, 45))    # 7:15am IST
    first = worker_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid}).get_json()["today"]
    pm_client.post(f"/api/attendance/{first['id']}/approve")
    worker_client.post("/api/attendance/check-out")

    monkeypatch.setattr("app.attendance.utcnow", lambda: datetime(2026, 10, 19, 1, 50))    # 7:20am IST
    second = worker_client.post("/api/attendance/check-in", json={**LOC, "project_id": pid}).get_json()["today"]
    assert second["status"] == "pending"
    assert pm_client.post(f"/api/attendance/{second['id']}/approve").status_code == 200


# ---------- marking yourself absent ahead of time (kohal, 2026-10-19: "For absent provide option within
# check in tab ... Absent should be inform 1 day before") ----------

def test_a_daily_wage_worker_can_mark_an_absence_for_a_future_day(app):
    worker_client, worker_user = daily_wage_user(app)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    res = worker_client.post("/api/attendance/absences", json={"for_date": tomorrow, "reason": "Family function"})
    assert res.status_code == 201
    body = res.get_json()["absence"]
    assert body["status"] == "pending" and body["reason"] == "Family function"


def test_absence_must_be_at_least_a_day_ahead(app):
    worker_client, worker_user = daily_wage_user(app)
    today = date.today().isoformat()
    res = worker_client.post("/api/attendance/absences", json={"for_date": today})
    assert res.status_code == 422 and "for_date" in res.get_json()["fields"]


def test_only_a_daily_wage_worker_can_request_an_absence(client):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    res = client.post("/api/attendance/absences", json={"for_date": tomorrow})
    assert res.status_code == 403


def test_duplicate_pending_absence_for_the_same_day_is_rejected(app):
    worker_client, worker_user = daily_wage_user(app)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    worker_client.post("/api/attendance/absences", json={"for_date": tomorrow})
    res = worker_client.post("/api/attendance/absences", json={"for_date": tomorrow})
    assert res.status_code == 409


def test_admin_and_project_manager_see_and_can_act_on_a_pending_absence(app, admin_client):
    worker_client, worker_user = daily_wage_user(app)
    manager = make_user("Priya Manager", role="project_manager")
    pm_client = signed_in(app, manager)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    record_id = worker_client.post("/api/attendance/absences", json={"for_date": tomorrow}).get_json()["absence"]["id"]

    assert admin_client.get("/api/attendance/absences").get_json()["absences"][0]["id"] == record_id
    assert pm_client.get("/api/attendance/absences").get_json()["absences"][0]["id"] == record_id

    res = pm_client.post(f"/api/attendance/absences/{record_id}/approve")
    assert res.status_code == 200 and res.get_json()["absence"]["status"] == "approved"
    assert pm_client.post(f"/api/attendance/absences/{record_id}/approve").status_code == 409


def test_someone_without_approval_rights_cannot_see_or_act_on_absences(app, client):
    worker_client, worker_user = daily_wage_user(app)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    record_id = worker_client.post("/api/attendance/absences", json={"for_date": tomorrow}).get_json()["absence"]["id"]
    assert client.get("/api/attendance/absences").status_code == 403
    assert client.post(f"/api/attendance/absences/{record_id}/approve").status_code == 403


def test_state_reports_whether_this_person_can_mark_absent(app, client):
    worker_client, worker_user = daily_wage_user(app)
    assert client.get("/api/attendance/state").get_json()["can_mark_absent"] is False
    assert worker_client.get("/api/attendance/state").get_json()["can_mark_absent"] is True


def test_attendance_approvals_lists_only_what_this_person_can_act_on(app, client):
    with app.app_context():
        pid = make_project().id
    check_in(client, project_id=pid)

    manager = signed_in(app, make_user("Priya Manager", role="project_manager"))
    assert len(manager.get("/api/attendance/approvals").get_json()["approvals"]) == 1

    welder = signed_in(app, make_user("Wendy Welder", role="welder"))
    assert welder.get("/api/attendance/approvals").get_json()["approvals"] == []

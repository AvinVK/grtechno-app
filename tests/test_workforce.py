"""Manpower & staff and the Attendance sheet: two admin-only pages over the same worker attendance data."""

from datetime import date, timedelta

from app.extensions import db
from app.models import Client, Project, Worker, WorkerAttendance


def make(name, category="manpower", present=(), absent=(), first_seen_days_ago=400, project=None):
    """A worker with a present row `present` days ago and an explicit absent row `absent` days ago."""
    today = date.today()
    worker = Worker(name=name, category=category, first_seen=today - timedelta(days=first_seen_days_ago))
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

def test_pages_and_api_are_admin_only(client, manager_client, accounts_client, admin_client, anon):
    for who in (client, manager_client, accounts_client):
        for url in ("/workforce", "/attendance-sheet", "/api/workforce", "/api/workforce/1"):
            assert who.get(url).status_code == 403
    assert anon.get("/workforce").status_code == 302 and anon.get("/api/workforce").status_code == 401
    roster = admin_client.get("/workforce").get_data(as_text=True)
    sheet = admin_client.get("/attendance-sheet").get_data(as_text=True)
    assert 'data-mode="roster"' in roster and 'people.js' in roster
    assert 'data-mode="sheet"' in sheet


def test_both_are_in_the_admin_menu_only(client, admin_client):
    for label in ("Manpower &amp; staff", "Attendance sheet"):
        assert label not in client.get("/me").get_data(as_text=True)
        assert label in admin_client.get("/me").get_data(as_text=True)


def test_attendance_is_called_your_attendance_in_the_menu(client):
    assert "Your attendance" in client.get("/me").get_data(as_text=True)


# ---------- the two groups ----------

def test_people_are_split_into_manpower_and_staff(admin_client, app):
    with app.app_context():
        make("Sunny Pipe Welder GR", present=(0,))
        make("Kuldip Gaurd HR", category="staff", present=(0,))
    body = admin_client.get("/api/workforce").get_json()
    assert [p["name"] for p in body["manpower"]] == ["Sunny Pipe Welder GR"]
    assert [p["name"] for p in body["staff"]] == ["Kuldip Gaurd HR"]


def test_deployed_is_their_most_recent_present_day(admin_client, app):
    with app.app_context():
        c = Client(name="Kalyani")
        p = Project(client=c, title="Sprinkler install", status="running")
        db.session.add_all([c, p])
        db.session.commit()
        make("On site", present=(3,), absent=(0,), project=p)
        make("Never came", absent=(1,))
    rows = by_name(admin_client.get("/api/workforce").get_json()["manpower"])
    deployed = rows["On site"]["deployed"]
    assert deployed["date"] == (date.today() - timedelta(days=3)).isoformat()      # the absent day after is skipped
    assert deployed["project_title"] == "Sprinkler install" and deployed["map_url"]
    assert rows["Never came"]["deployed"] is None


def test_last_week_dots_never_mark_days_past_the_data_as_absent(admin_client, app):
    with app.app_context():
        make("Sunny", present=(2, 4))                  # the latest data anyone has is 2 days ago
    week = by_name(admin_client.get("/api/workforce").get_json()["manpower"])["Sunny"]["week"]
    assert [d["status"] for d in week] == ["absent", "absent", "present", "absent", "present", "none", "none"]
    assert week[-1]["date"] == date.today().isoformat()


def test_sheet_counts_present_days_from_when_they_first_turned_up(admin_client, app):
    with app.app_context():
        make("Old hand", present=(0, 1, 2, 3), first_seen_days_ago=400)
        make("New joiner", present=(0, 1), first_seen_days_ago=1)
    body = admin_client.get("/api/workforce").get_json()
    rows = by_name(body["manpower"])
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


def test_no_data_means_no_period(admin_client, app):
    with app.app_context():
        wid = make("Nobody yet")
    body = admin_client.get("/api/workforce").get_json()
    assert body["period"] is None and body["data_until"] is None
    assert body["manpower"][0]["days"] == 0 and {d["status"] for d in body["manpower"][0]["week"]} == {"none"}
    assert admin_client.get(f"/api/workforce/{wid}").get_json()["period"] is None


# ---------- admin can add and remove a person ----------

def test_admin_adds_a_person_ahead_of_the_next_import(admin_client):
    res = admin_client.post("/api/workforce", json={"name": "New Hire", "category": "staff"})
    assert res.status_code == 201
    body = res.get_json()["worker"]
    assert body["name"] == "New Hire" and body["category"] == "staff" and body["source"] == "manual"
    listed = admin_client.get("/api/workforce").get_json()
    assert by_name(listed["staff"])["New Hire"]["id"] == body["id"]


def test_adding_a_person_requires_a_name_and_a_valid_category(admin_client):
    res = admin_client.post("/api/workforce", json={"name": "", "category": "staff"})
    assert res.status_code == 422 and "name" in res.get_json()["fields"]
    res = admin_client.post("/api/workforce", json={"name": "Someone", "category": "manager"})
    assert res.status_code == 422 and "category" in res.get_json()["fields"]


def test_only_the_admin_can_add_or_remove_a_person(client, manager_client, accounts_client):
    for who in (client, manager_client, accounts_client):
        assert who.post("/api/workforce", json={"name": "X", "category": "staff"}).status_code == 403
        assert who.delete("/api/workforce/1").status_code == 403


def test_admin_removes_a_person_and_their_attendance_goes_with_them(admin_client, app):
    with app.app_context():
        wid = make("Leaving Soon", present=(0, 1))
    assert admin_client.delete(f"/api/workforce/{wid}").status_code == 204
    assert admin_client.get(f"/api/workforce/{wid}").status_code == 404
    listed = admin_client.get("/api/workforce").get_json()
    assert "Leaving Soon" not in by_name(listed["manpower"])
    assert admin_client.delete("/api/workforce/9999").status_code == 404


def test_removing_a_person_clears_their_name_from_leads_they_were_picked_on(admin_client, admin, app):
    from app.models import Lead
    with app.app_context():
        wid = make("Picked On A Lead", category="staff")
        lead = Lead(company="Some Co", contact_name="X", phone="9800000000", enquired_by_id=wid, owner_code=admin.code)
        db.session.add(lead)
        db.session.commit()
        lead_id = lead.id

    assert admin_client.delete(f"/api/workforce/{wid}").status_code == 204
    with app.app_context():
        kept = db.session.get(Lead, lead_id)
        assert kept is not None and kept.enquired_by_id is None

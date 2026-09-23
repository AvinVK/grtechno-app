from datetime import date, timedelta

from app.extensions import db
from app.models import Worker, WorkerAttendance


def make_staff(name="Kuldip Gaurd HR", days_ago=(0, 1)):
    staff = Worker(name=name, category="staff", source="whatsapp",
                    first_seen=date.today() - timedelta(days=400), last_seen=date.today())
    db.session.add(staff)
    db.session.flush()
    for d in days_ago:
        db.session.add(WorkerAttendance(worker=staff, work_date=date.today() - timedelta(days=d)))
    db.session.commit()
    return staff


# ---------- admin only ----------

def test_staff_page_and_api_are_admin_only(client, manager_client, accounts_client, admin_client):
    for who in (client, manager_client, accounts_client):
        assert who.get("/staff").status_code == 403
        assert who.get("/api/staff").status_code == 403
    assert admin_client.get("/staff").status_code == 200
    assert admin_client.get("/api/staff").status_code == 200


def test_staff_needs_sign_in(anon):
    assert anon.get("/staff").status_code == 302
    assert anon.get("/api/staff").status_code == 401


def test_staff_page_is_titled_and_not_part_of_leads(admin_client):
    html = admin_client.get("/staff").get_data(as_text=True)
    assert "staff.js" in html
    assert '<span class="brand-mark" aria-hidden="true"></span>Staff list</a>' in html
    assert "app.js" not in html and "bottom-nav" not in html


def test_staff_list_is_only_in_the_admin_menu(client, admin_client):
    assert "Staff list" not in client.get("/").get_data(as_text=True)
    assert "Staff list" in admin_client.get("/").get_data(as_text=True)


# ---------- listing and detail ----------

def test_list_shows_each_staff_member_with_a_days_present_count(admin_client, app):
    with app.app_context():
        make_staff("Kuldip Gaurd HR", days_ago=(0, 1, 2))
        make_staff("Ashish Sutone", days_ago=())
    body = admin_client.get("/api/staff").get_json()
    by_name = {w["name"]: w for w in body["workers"]}
    assert by_name["Kuldip Gaurd HR"]["days_present"] == 3
    assert by_name["Ashish Sutone"]["days_present"] == 0
    assert body["window_days"] == 14


def test_staff_detail_lists_their_attendance(admin_client, app):
    with app.app_context():
        staff = make_staff("Kuldip Gaurd HR", days_ago=(0, 1))
        staff_id = staff.id
    body = admin_client.get(f"/api/staff/{staff_id}").get_json()
    assert body["worker"]["name"] == "Kuldip Gaurd HR" and body["worker"]["category"] == "staff"
    assert len(body["attendance"]) == 2
    assert body["attendance"][0]["work_date"] == date.today().isoformat()   # newest first


def test_a_missing_staff_member_is_404(admin_client):
    assert admin_client.get("/api/staff/999999").status_code == 404


def test_an_absent_day_needs_no_check_in(admin_client, app):
    """"Aaj hum nahi aayenge" (won't come today) - Deepak's own message, no check-in that day."""
    with app.app_context():
        staff = Worker(name="Deepak GR WP", category="staff")
        db.session.add(staff)
        db.session.flush()
        db.session.add(WorkerAttendance(
            worker=staff, work_date=date.today(), status="absent",
            note='Deepak GR WP: "Aaj hum nahi aayenge"',
        ))
        db.session.commit()
        staff_id = staff.id
    row = admin_client.get(f"/api/staff/{staff_id}").get_json()["attendance"][0]
    assert row["status"] == "absent" and row["check_in_at"] is None and row["hours"] is None

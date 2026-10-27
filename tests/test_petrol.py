"""Petrol payment (kohal, 2026-10-27): an odometer photo + reading at every check-in and check-out for an
employee it's switched on for, approved once per session by the admin or the project manager, the amount
being the kilometres between the two readings times constants.PETROL_RATE_PER_KM, and the photos deleted a
day later once decided. See app/petrol.py."""

import io
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import Attendance, Client, PetrolEntry, Project, Worker
from conftest import make_user, signed_in

LOC = {"lat": 21.1458, "lng": 79.0882}


@pytest.fixture(autouse=True)
def _own_upload_dir(app, tmp_path):
    """Odometer photos in these tests go to a throwaway folder, not the real instance/uploads."""
    app.config["UPLOAD_DIR"] = tmp_path


def photo(name="odo.jpg"):
    return (io.BytesIO(b"fake-image-bytes"), name, "image/jpeg")


def petrol_user(app, name="Rider Ravi", enabled=True):
    user = make_user(name)
    db.session.add(Worker(name=name, category="manpower", user_code=user.code, petrol_enabled=enabled))
    db.session.commit()
    return signed_in(app, user)


def check_in(client, reading="12000", with_photo=True, **extra):
    data = {**{k: str(v) for k, v in LOC.items()}, **extra}
    if reading is not None:
        data["odometer_reading"] = reading
    if with_photo:
        data["odometer_photo"] = photo()
    return client.post("/api/attendance/check-in", data=data, content_type="multipart/form-data")


def check_out(client, reading="12018", with_photo=True):
    data = {}
    if reading is not None:
        data["odometer_reading"] = reading
    if with_photo:
        data["odometer_photo"] = photo()
    return client.post("/api/attendance/check-out", data=data, content_type="multipart/form-data")


def test_the_attendance_state_says_when_petrol_payment_is_on(app):
    on = petrol_user(app, "Rider On")
    off = petrol_user(app, "Rider Off", enabled=False)
    assert on.get("/api/attendance/state").get_json()["petrol_required"] is True
    assert off.get("/api/attendance/state").get_json()["petrol_required"] is False


def test_checking_in_without_a_reading_or_a_photo_is_refused_when_petrol_is_on(app):
    who = petrol_user(app)
    no_photo = check_in(who, with_photo=False)
    assert no_photo.status_code == 422 and "odometer_photo" in no_photo.get_json()["fields"]
    no_reading = check_in(who, reading=None)
    assert no_reading.status_code == 422 and "odometer_reading" in no_reading.get_json()["fields"]
    decimal = check_in(who, reading="120.5")
    assert decimal.status_code == 422                       # whole numbers only
    assert Attendance.query.count() == 0


def test_someone_without_petrol_payment_checks_in_as_before(app):
    who = petrol_user(app, enabled=False)
    assert who.post("/api/attendance/check-in", json=LOC).status_code == 201
    assert who.post("/api/attendance/check-out").status_code == 200
    assert PetrolEntry.query.count() == 0


def test_check_in_and_check_out_with_odometer_make_one_entry_with_the_km_and_amount(app):
    who = petrol_user(app)
    assert check_in(who, "12000").status_code == 201
    entry = PetrolEntry.query.one()
    assert entry.in_reading == 12000 and entry.in_photo and entry.out_reading is None
    assert check_out(who, "12018").status_code == 200
    db.session.refresh(entry)
    assert entry.out_reading == 12018 and entry.out_photo
    assert entry.km == 18 and float(entry.amount) == 72.0           # 18 km x 4


def test_checking_out_needs_a_reading_and_photo_that_is_not_lower_than_at_check_in(app):
    who = petrol_user(app)
    check_in(who, "12000")
    assert check_out(who, with_photo=False).status_code == 422
    assert check_out(who, reading=None).status_code == 422
    lower = check_out(who, "11999")
    assert lower.status_code == 422 and "12000" in lower.get_json()["fields"]["odometer_reading"]
    assert Attendance.query.one().check_out_at is None             # still checked in


def test_only_the_admin_or_the_projects_manager_approve_and_the_amount_counts_after(app, admin_client, manager_client):
    client = Client(name="Sunrise Hospital")
    db.session.add(client)
    db.session.flush()
    project = Project(client=client, title="Sprinkler install", status="running")
    db.session.add(project)
    db.session.commit()
    who = petrol_user(app)
    check_in(who, "500", project_id=project.id)
    check_out(who, "520")
    entry = PetrolEntry.query.one()

    # Not yet visible as approved money; the rider can't approve their own.
    assert who.post(f"/api/petrol/{entry.id}/approve").status_code == 403
    pending = admin_client.get("/api/petrol/approvals").get_json()["approvals"]
    assert [p["id"] for p in pending] == [entry.id] and pending[0]["amount"] == 80.0
    assert pending[0]["in_photo_url"].startswith("/uploads/odometer/")

    # Approving is once, and only for someone who can see that project (the manager here is a plain PM).
    assert admin_client.post(f"/api/petrol/{entry.id}/approve").status_code == 200
    assert admin_client.post(f"/api/petrol/{entry.id}/approve").status_code == 409
    mine = who.get("/api/petrol/me").get_json()
    assert mine["approved_total"] == 80.0 and mine["month_total"] == 80.0 and mine["month_km"] == 20


def test_a_rejected_entry_adds_no_money(app, admin_client):
    who = petrol_user(app)
    check_in(who, "100")
    check_out(who, "150")
    entry = PetrolEntry.query.one()
    assert admin_client.post(f"/api/petrol/{entry.id}/reject").status_code == 200
    mine = who.get("/api/petrol/me").get_json()
    assert mine["approved_total"] == 0 and mine["entries"][0]["status"] == "rejected"


def test_an_open_session_cannot_be_approved_yet(app, admin_client):
    who = petrol_user(app)
    check_in(who, "100")
    entry = PetrolEntry.query.one()
    assert admin_client.post(f"/api/petrol/{entry.id}/approve").status_code == 409
    assert admin_client.get("/api/petrol/approvals").get_json()["approvals"] == []


def test_photos_of_a_decided_entry_are_deleted_the_next_day_but_the_readings_stay(app, admin_client):
    who = petrol_user(app)
    check_in(who, "100")
    check_out(who, "130")
    decided = PetrolEntry.query.one()
    admin_client.post(f"/api/petrol/{decided.id}/approve")

    uploads = app.config["UPLOAD_DIR"] / "odometer"
    stored = [p.name for p in uploads.iterdir()]
    assert len(stored) == 2
    # Same day: nothing is removed yet.
    who.get("/api/attendance/state")
    assert len(list(uploads.iterdir())) == 2

    decided = PetrolEntry.query.one()
    decided.work_date = decided.work_date - timedelta(days=1)
    db.session.commit()
    who.get("/api/attendance/state")
    assert list(uploads.iterdir()) == []
    decided = PetrolEntry.query.one()
    assert decided.in_photo is None and decided.out_photo is None
    assert decided.in_reading == 100 and decided.out_reading == 130 and float(decided.amount) == 120.0


def test_an_undecided_entry_keeps_its_photos_past_the_day(app):
    who = petrol_user(app)
    check_in(who, "100")
    check_out(who, "130")
    entry = PetrolEntry.query.one()
    entry.work_date = entry.work_date - timedelta(days=2)
    db.session.commit()
    who.get("/api/attendance/state")
    assert PetrolEntry.query.one().in_photo is not None


def test_employee_management_can_switch_petrol_on_and_the_page_is_for_the_right_people(app, admin_client, accounts_client):
    worker = Worker(name="Switch Me", category="manpower")
    db.session.add(worker)
    db.session.commit()
    res = admin_client.patch(f"/api/workforce/{worker.id}", json={"petrol_enabled": True})
    assert res.status_code == 200
    assert db.session.get(Worker, worker.id).petrol_enabled is True
    listing = accounts_client.get("/api/petrol").get_json()
    assert [w["worker_name"] for w in listing["workers"]] == ["Switch Me"]
    off = petrol_user(app, "Nobody", enabled=False)
    assert off.get("/petrol").status_code == 403
    assert off.get("/api/petrol").status_code == 403

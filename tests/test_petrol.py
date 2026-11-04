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


# ---------- asking for the cash (kohal, 2026-10-30) ----------

def _approved_day(app, admin_client, name="Rider Ravi", start="1000", end="1020"):
    who = petrol_user(app, name)
    check_in(who, start)
    check_out(who, end)
    entry = PetrolEntry.query.order_by(PetrolEntry.id.desc()).first()
    admin_client.post(f"/api/petrol/{entry.id}/approve")
    return who, entry.id


def test_an_approved_day_can_be_asked_for_in_cash_only_by_its_owner_and_only_once(app, admin_client):
    who, eid = _approved_day(app, admin_client)
    other = petrol_user(app, "Someone Else")
    assert other.post(f"/api/petrol/{eid}/request-cash").status_code == 404           # not theirs
    assert who.post(f"/api/petrol/{eid}/request-cash").status_code == 200
    assert who.post(f"/api/petrol/{eid}/request-cash").status_code == 409             # already asked
    mine = who.get("/api/petrol/me").get_json()
    assert mine["entries"][0]["cash_status"] == "requested" and mine["unpaid_total"] == 80.0


def test_a_day_that_is_not_approved_cannot_be_asked_for(app):
    who = petrol_user(app)
    check_in(who, "100")
    check_out(who, "150")
    eid = PetrolEntry.query.one().id
    assert who.post(f"/api/petrol/{eid}/request-cash").status_code == 409


def test_only_the_admin_pays_it_and_must_say_how(app, admin_client, accounts_client, manager_client):
    """kohal, 2026-11-02: "for petrol also do it admin-style" - paying is going through the bank accounts, so it is the
    admin's alone; the accountant can look at the list."""
    who, eid = _approved_day(app, admin_client)
    who.post(f"/api/petrol/{eid}/request-cash")

    waiting = accounts_client.get("/api/petrol/requests").get_json()
    assert [p["id"] for p in waiting["pending"]] == [eid] and waiting["payment_modes"] == ["VK PP BB", "GR CANARA BANK", "VK GPAY SBI", "GR BB", "CASH", "GR BOB"]
    assert waiting["can_decide"] is False
    assert manager_client.get("/api/petrol/requests").status_code == 403
    assert manager_client.post(f"/api/petrol/requests/{eid}/approve", json={"payment_mode": "CASH"}).status_code == 403
    assert who.post(f"/api/petrol/requests/{eid}/approve", json={"payment_mode": "CASH"}).status_code == 403
    assert accounts_client.post(f"/api/petrol/requests/{eid}/approve", json={"payment_mode": "GR BB"}).status_code == 403
    assert accounts_client.post(f"/api/petrol/requests/{eid}/reject").status_code == 403
    assert admin_client.get("/api/petrol/requests").get_json()["can_decide"] is True

    no_mode = admin_client.post(f"/api/petrol/requests/{eid}/approve", json={})
    assert no_mode.status_code == 422 and "payment_mode" in no_mode.get_json()["fields"]
    assert admin_client.post(f"/api/petrol/requests/{eid}/approve", json={"payment_mode": "Cheque"}).status_code == 422
    done = admin_client.post(f"/api/petrol/requests/{eid}/approve", json={"payment_mode": "GR BB"})
    assert done.status_code == 200 and done.get_json()["entry"]["cash_status"] == "paid"

    mine = who.get("/api/petrol/me").get_json()
    assert mine["paid_total"] == 80.0 and mine["unpaid_total"] == 0.0
    assert mine["entries"][0]["cash_mode"] == "GR BB" and mine["entries"][0]["cash_decided_by_name"] == "grtechno"
    assert admin_client.post(f"/api/petrol/requests/{eid}/approve", json={"payment_mode": "CASH"}).status_code == 409
    hist = admin_client.get("/api/petrol/requests").get_json()
    assert hist["pending"] == [] and [h["id"] for h in hist["history"]] == [eid]


def test_a_petrol_request_carries_who_gets_paid_for_the_payment_app(app, admin_client):
    from app.extensions import db
    from app.models import Worker
    who, eid = _approved_day(app, admin_client)
    with app.app_context():
        w = Worker.query.filter_by(petrol_enabled=True).first()
        w.upi_id, w.phone = "rider@ybl", "9000000001"
        db.session.commit()
    who.post(f"/api/petrol/{eid}/request-cash")
    row = admin_client.get("/api/petrol/requests").get_json()["pending"][0]
    assert row["payee"] == {"upi_id": "rider@ybl", "phone": "9000000001"}


def test_a_rejected_cash_request_can_be_asked_for_again(app, admin_client):
    who, eid = _approved_day(app, admin_client)
    who.post(f"/api/petrol/{eid}/request-cash")
    assert admin_client.post(f"/api/petrol/requests/{eid}/reject").status_code == 200
    assert who.get("/api/petrol/me").get_json()["entries"][0]["cash_status"] == "rejected"
    assert who.post(f"/api/petrol/{eid}/request-cash").status_code == 200
    assert who.get("/api/petrol/me").get_json()["entries"][0]["cash_status"] == "requested"


def test_the_me_tile_counts_cash_waiting_to_be_paid(app, admin_client):
    who, eid = _approved_day(app, admin_client)
    who.post(f"/api/petrol/{eid}/request-cash")
    assert "1 to pay" in admin_client.get("/me").get_data(as_text=True)


# ---------- petrol cash that accumulates (kohal, 2026-11-04) ----------

def _two_approved_days(app, admin_client):
    """Rider Ravi with two approved days, 20 km each - 80 + 80 = 160 owed."""
    who = petrol_user(app, "Rider Ravi")
    for start, end in (("1000", "1020"), ("1100", "1120")):
        check_in(who, start)
        check_out(who, end)
        entry = PetrolEntry.query.order_by(PetrolEntry.id.desc()).first()
        admin_client.post(f"/api/petrol/{entry.id}/approve")
        # a second check-in the same day is refused, so move the first session to an earlier date
        if start == "1000":
            entry.work_date = entry.work_date.replace(day=1) if entry.work_date.day != 1 else entry.work_date.replace(day=2)
            entry.attendance.work_date = entry.work_date
            from app.extensions import db
            db.session.commit()
    return who


def test_approved_petrol_accumulates_into_one_balance_to_ask_for(app, admin_client):
    who = _two_approved_days(app, admin_client)
    mine = who.get("/api/petrol/me").get_json()
    assert mine["unpaid_total"] == 160.0 and mine["can_request_up_to"] == 160.0 and mine["settled"] is False


def test_a_payout_defaults_to_the_whole_balance_and_only_one_waits_at_a_time(app, admin_client):
    who = _two_approved_days(app, admin_client)
    assert who.post("/api/petrol/payouts", json={}).status_code == 201
    mine = who.get("/api/petrol/me").get_json()
    assert mine["payouts"][0]["amount"] == 160.0 and mine["requested_total"] == 160.0 and mine["can_request_up_to"] == 0.0
    assert who.post("/api/petrol/payouts", json={"amount": "10"}).status_code == 409


def test_a_payout_cannot_be_more_than_what_is_owed(app, admin_client):
    who = _two_approved_days(app, admin_client)
    res = who.post("/api/petrol/payouts", json={"amount": "161"})
    assert res.status_code == 422 and "amount" in res.get_json()["fields"]
    assert who.post("/api/petrol/payouts", json={"amount": "0"}).status_code == 422


def test_paying_part_of_a_payout_settles_that_part_and_the_rest_stays_owed(app, admin_client):
    who = _two_approved_days(app, admin_client)
    who.post("/api/petrol/payouts", json={"amount": "100"})
    pid = who.get("/api/petrol/me").get_json()["payouts"][0]["id"]
    res = admin_client.post(f"/api/petrol/payouts/{pid}/approve", json={"amount": "60", "payment_mode": "GR BB"})
    assert res.status_code == 200
    mine = who.get("/api/petrol/me").get_json()
    assert mine["paid_total"] == 60.0 and mine["unpaid_total"] == 100.0 and mine["settled"] is False
    assert mine["can_request_up_to"] == 100.0                                    # the unpaid 40 of that ask can be asked again
    rows = admin_client.get("/api/accounts/detail", query_string={"name": "GR BB"}).get_json()["entries"]
    assert [(r["reason"], r["kind"], r["amount"]) for r in rows] == [("Petrol", "debit", 60.0)]


def test_paying_the_whole_balance_shows_settled(app, admin_client):
    who = _two_approved_days(app, admin_client)
    who.post("/api/petrol/payouts", json={})
    pid = who.get("/api/petrol/me").get_json()["payouts"][0]["id"]
    admin_client.post(f"/api/petrol/payouts/{pid}/approve", json={"payment_mode": "GR BB"})      # amount defaults to what was asked
    mine = who.get("/api/petrol/me").get_json()
    assert mine["unpaid_total"] == 0.0 and mine["settled"] is True and mine["payouts"][0]["status"] == "paid"


def test_only_the_admin_pays_a_payout_with_an_account_and_not_more_than_asked(app, admin_client, accounts_client):
    who = _two_approved_days(app, admin_client)
    who.post("/api/petrol/payouts", json={"amount": "100"})
    pid = who.get("/api/petrol/me").get_json()["payouts"][0]["id"]
    assert accounts_client.post(f"/api/petrol/payouts/{pid}/approve", json={"payment_mode": "GR BB"}).status_code == 403
    assert admin_client.post(f"/api/petrol/payouts/{pid}/approve", json={}).status_code == 422                 # needs an account
    assert admin_client.post(f"/api/petrol/payouts/{pid}/approve", json={"payment_mode": "GR BB", "amount": "101"}).status_code == 422
    assert admin_client.post(f"/api/petrol/payouts/{pid}/approve", json={"payment_mode": "GR BB", "amount": "100"}).status_code == 200
    assert admin_client.post(f"/api/petrol/payouts/{pid}/approve", json={"payment_mode": "GR BB"}).status_code == 409


def test_a_rejected_payout_frees_the_balance_to_be_asked_again(app, admin_client):
    who = _two_approved_days(app, admin_client)
    who.post("/api/petrol/payouts", json={})
    pid = who.get("/api/petrol/me").get_json()["payouts"][0]["id"]
    assert admin_client.post(f"/api/petrol/payouts/{pid}/reject").status_code == 200
    assert who.get("/api/petrol/me").get_json()["can_request_up_to"] == 160.0
    assert who.post("/api/petrol/payouts", json={}).status_code == 201


def test_the_admins_request_list_carries_payouts_and_the_waiting_count(app, admin_client):
    who = _two_approved_days(app, admin_client)
    who.post("/api/petrol/payouts", json={"amount": "50"})
    data = admin_client.get("/api/petrol/requests").get_json()
    assert data["payouts"][0]["amount"] == 50.0 and data["payouts"][0]["balance"] == 160.0 and "payee" in data["payouts"][0]
    assert admin_client.get("/api/petrol").get_json()["cash_waiting"] == 1

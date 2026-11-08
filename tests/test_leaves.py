"""Leave for salaried employees (kohal, 2026-11-08): 6 sick and 12 casual a year, built up monthly over an April-March year, sick
leave carried forward; asked for from Attendance, approved by the admin, who decides whether days beyond the balance are paid.
See app/leaves.py."""

from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.leaves import balance, paid_leave_days
from app.models import LeaveRequest, Worker, WorkerAttendance
from tests.conftest import make_user, signed_in

TODAY = date(2026, 11, 8)


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr("app.leaves.today_local", lambda: TODAY)


def _employee(app, name="Ritesh", kind="regular", joining=None):
    """A salaried employee with a login of their own; returns (client, worker id)."""
    with app.app_context():
        user = make_user(name)
        w = Worker(name=name, category="staff", employment_type=kind, wage_amount=Decimal("31000"), user_code=user.code, joining_date=joining)
        db.session.add(w)
        db.session.commit()
        return signed_in(app, user), w.id


def _ask(client, kind="casual", start="2026-11-10", end=None, reason="Family function"):
    return client.post("/api/leaves", json={"kind": kind, "start_date": start, "end_date": end or start, "reason": reason})


def _worker(app, wid):
    return db.session.get(Worker, wid)


def test_leave_builds_up_monthly_and_only_sick_leave_carries_into_the_next_year(app):
    _, wid = _employee(app)
    with app.app_context():
        w = _worker(app, wid)
        b = balance(w, date(2026, 11, 8))                       # October and November so far (nothing before payroll's 1 Oct)
        assert b["year"] == "2026-27" and b["casual"]["balance"] == 2 and b["sick"]["balance"] == 1.0
        b = balance(w, date(2027, 3, 31))                       # Oct-Mar: six months
        assert b["casual"]["balance"] == 6 and b["sick"]["balance"] == 3.0
        b = balance(w, date(2027, 4, 10))                       # a new year: casual starts again, sick brings its 3 along
        assert b["year"] == "2027-28" and b["casual"]["balance"] == 1 and b["sick"]["carried"] == 3.0 and b["sick"]["balance"] == 3.5


def test_a_new_joiner_builds_up_from_their_joining_month(app):
    _, wid = _employee(app, joining=date(2027, 1, 20))
    with app.app_context():
        assert balance(_worker(app, wid), date(2027, 3, 1))["casual"]["balance"] == 3       # Jan, Feb, Mar


def test_asking_for_leave_counts_working_days_only(app):
    client, wid = _employee(app)
    r = _ask(client, start="2026-11-09", end="2026-11-15")      # Mon 9th to Sun 15th
    assert r.status_code == 201
    req = r.get_json()["request"]
    assert (req["status"], req["days"], req["kind"]) == ("pending", 6, "casual")
    data = client.get("/api/leaves/me").get_json()
    assert data["balance"]["casual"]["balance"] == 2 and len(data["requests"]) == 1             # nothing comes off until approved


def test_approval_takes_it_off_the_balance(app, admin_client):
    client, wid = _employee(app)
    lid = _ask(client, start="2026-11-10", end="2026-11-11").get_json()["request"]["id"]
    assert admin_client.get("/api/leaves/admin").get_json()["pending"][0]["available"] == 2
    r = admin_client.post(f"/api/leaves/{lid}/approve", json={})
    assert r.status_code == 200 and r.get_json()["request"]["deducted_days"] == 2
    assert client.get("/api/leaves/me").get_json()["balance"]["casual"]["balance"] == 0
    tally = next(p for p in admin_client.get("/api/leaves/admin").get_json()["people"] if p["id"] == wid)
    assert tally["this_month"] == {"sick": 0, "casual": 2, "unpaid": 0}


def test_days_beyond_the_balance_are_the_admins_call(app, admin_client):
    client, wid = _employee(app)
    lid = _ask(client, start="2026-11-10", end="2026-11-13").get_json()["request"]["id"]       # 4 days, 2 casual left
    r = admin_client.post(f"/api/leaves/{lid}/approve", json={})
    assert r.status_code == 422 and r.get_json()["extra_days"] == 2
    r = admin_client.post(f"/api/leaves/{lid}/approve", json={"extra": "unpaid"})
    assert (r.get_json()["request"]["deducted_days"], r.get_json()["request"]["unpaid_days"]) == (2, 2)
    with app.app_context():
        days = paid_leave_days(_worker(app, wid), date(2026, 11, 1), date(2026, 11, 30))
        assert [paid for _, (_, paid) in sorted(days.items())] == [True, True, False, False]      # paid first, unpaid last

    lid2 = _ask(client, kind="sick", start="2026-11-16", end="2026-11-18").get_json()["request"]["id"]   # 3 days, 1 sick left
    r = admin_client.post(f"/api/leaves/{lid2}/approve", json={"extra": "paid"})
    assert (r.get_json()["request"]["deducted_days"], r.get_json()["request"]["extra_paid_days"], r.get_json()["request"]["unpaid_days"]) == (1, 2, 0)


def test_paid_leave_is_a_paid_day_and_unpaid_leave_is_cut_like_an_absence(app, admin_client):
    from app.payroll import salaried_month
    client, wid = _employee(app)
    with app.app_context():
        w = _worker(app, wid)
        for day in range(1, 32):                                 # present every working day of October but the 12th-16th
            if date(2026, 10, day).weekday() != 6 and day not in (12, 13, 14, 15, 16):
                db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
        db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 11, 2)))                   # October's data is complete
        # 12th-16th on casual leave: 2 off the balance... set up directly, as the admin would have approved it
        db.session.add(LeaveRequest(worker_id=w.id, kind="casual", start_date=date(2026, 10, 12), end_date=date(2026, 10, 16), days=5,
                                    status="approved", deducted_days=1, extra_paid_days=2, unpaid_days=2))
        db.session.commit()
        m = salaried_month(_worker(app, wid), 2026, 10, date(2026, 11, 2))
        assert m["absent"] == 2 and m["present"] == 29 and m["net"] == 1000 * 29              # 31,000 / 31 = 1,000 a day


def test_the_payment_sheet_shows_the_months_leave_and_whats_left(app, admin_client):
    client, wid = _employee(app)
    lid = _ask(client, kind="sick", start="2026-11-10").get_json()["request"]["id"]
    admin_client.post(f"/api/leaves/{lid}/approve", json={})
    row = next(r for r in admin_client.get("/api/payroll/sheet?month=2026-11").get_json()["rows"] if r["id"] == wid)
    assert (row["sick_leave"], row["casual_leave"], row["sick_balance"], row["casual_balance"]) == (1, 0, 0.0, 2)
    october = next(r for r in admin_client.get("/api/payroll/sheet?month=2026-10").get_json()["rows"] if r["id"] == wid)
    assert (october["sick_leave"], october["sick_balance"], october["casual_balance"]) == (0, 0.5, 1)   # as at 31 Oct


def test_what_cannot_be_asked_for(app, admin_client):
    client, wid = _employee(app)
    assert _ask(client, kind="holiday").status_code == 422
    assert _ask(client, start="2026-11-12", end="2026-11-10").status_code == 422
    assert _ask(client, start="2026-09-01").status_code == 422                                  # before leave started in the app
    assert _ask(client, start="2027-03-30", end="2027-04-02").status_code == 422                # across two leave years
    assert _ask(client, start="2026-11-15").status_code == 422                                  # a Sunday only
    assert _ask(client, start="2026-11-10", end="2026-11-12").status_code == 201
    assert _ask(client, start="2026-11-12").status_code == 422                                  # overlaps the first
    daily, _ = _employee(app, "Deepak Daily", kind="daily_wages")
    assert _ask(daily).status_code == 403
    assert daily.get("/api/leaves/me").status_code == 403
    assert admin_client.post("/api/leaves", json={"kind": "sick", "start_date": "2026-11-10"}).status_code == 403


def test_withdrawing_and_who_decides(app, admin_client):
    client, wid = _employee(app)
    other, _ = _employee(app, "Someone Else")
    lid = _ask(client).get_json()["request"]["id"]
    assert other.post(f"/api/leaves/{lid}/cancel").status_code == 404                           # not theirs
    assert client.post(f"/api/leaves/{lid}/approve").status_code == 403                         # only the admin decides
    assert client.get("/api/leaves/admin").status_code == 403
    assert client.post(f"/api/leaves/{lid}/cancel").status_code == 200
    assert client.post(f"/api/leaves/{lid}/cancel").status_code == 409
    lid = _ask(client).get_json()["request"]["id"]
    assert admin_client.post(f"/api/leaves/{lid}/reject", json={"note": "Busy week"}).get_json()["request"]["status"] == "rejected"
    assert admin_client.post(f"/api/leaves/{lid}/approve", json={}).status_code == 409


def test_the_leave_subtab_is_there_for_salaried_employees_and_the_admin(app, admin_client, client):
    salaried, _ = _employee(app)
    assert 'data-can-leave="1"' in salaried.get("/attendance").data.decode()
    assert 'data-can-leave="0"' in client.get("/attendance").data.decode()
    assert 'data-leave-admin="1"' in admin_client.get("/attendance").data.decode()

"""Holidays (kohal, 2026-11-10: "give power to admin to declare a holiday on any particular day. once declared, that day should be a paid
leave for selected employees ... this above logic is for daily wages people. for salaried it will be for all the employees who are
salaried. have a subtab in attendance called holidays")."""

from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.holidays import HolidayBook
from app.leaves import working_days
from app.models import Holiday, HolidayWorker, Worker, WorkerAttendance
from app.timeutil import today_local


def _salaried(name, salary, absent_days=()):
    """Present every working day of October 2026 except `absent_days`."""
    w = Worker(name=name, category="staff", employment_type="regular", wage_amount=Decimal(salary))
    db.session.add(w)
    db.session.flush()
    for day in range(1, 32):
        if date(2026, 10, day).weekday() != 6 and day not in absent_days:
            db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
    return w


def _daily(name, rate="500", present=(), kind="daily_wages"):
    w = Worker(name=name, category="manpower", employment_type=kind, wage_amount=Decimal(rate))
    db.session.add(w)
    db.session.flush()
    for day in present:
        db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
    return w


def _pusher():
    p = Worker(name="Zed Pusher", category="manpower")
    db.session.add(p)
    db.session.flush()
    db.session.add(WorkerAttendance(worker=p, work_date=date(2026, 11, 1)))


def _holiday(day, name="Diwali", workers=()):
    h = Holiday(holiday_date=day, name=name)
    h.links = [HolidayWorker(worker_id=w.id) for w in workers]
    db.session.add(h)
    return h


def _sheet(client, month="2026-10"):
    return {r["name"]: r for r in client.get(f"/api/payroll/sheet?month={month}").get_json()["rows"]}


def _daily_sheet(client, period="2026-10-01"):
    return {r["name"]: r for r in client.get(f"/api/payroll/sheet/daily?period={period}").get_json()["rows"]}


# ---------- salaried: every holiday is a paid day ----------

def test_a_holiday_is_a_paid_day_for_every_salaried_employee(app, admin_client):
    with app.app_context():
        _salaried("Ankush", "31000", absent_days=(14,))                 # off on Wednesday 14 Oct
        _salaried("Rashmi", "31000", absent_days=(14, 15))
        _pusher()
        db.session.commit()
    before = _sheet(admin_client)
    assert (before["Ankush"]["absent"], before["Ankush"]["net"]) == (1, 30000)
    with app.app_context():
        _holiday(date(2026, 10, 14))
        db.session.commit()
    after = _sheet(admin_client)
    assert (after["Ankush"]["absent"], after["Ankush"]["net"], after["Ankush"]["holidays"]) == (0, 31000, 1)    # no cut for the holiday
    assert (after["Rashmi"]["absent"], after["Rashmi"]["net"]) == (1, 30000)                                      # 15th is still missed


def test_a_holiday_a_salaried_employee_came_in_on_is_not_paid_twice(app, admin_client):
    with app.app_context():
        _salaried("Ankush", "31000")
        _holiday(date(2026, 10, 14))
        _pusher()
        db.session.commit()
    row = _sheet(admin_client)["Ankush"]
    assert (row["present"], row["absent"], row["net"]) == (31, 0, 31000)


# ---------- daily wages: only the people picked ----------

def test_a_holiday_is_paid_to_the_daily_wage_staff_picked_and_nobody_else(app, admin_client):
    with app.app_context():
        picked = _daily("Sita", "500", present=(1, 2, 3))
        _daily("Gita", "500", present=(1, 2, 3))
        _holiday(date(2026, 10, 8), "Eid", workers=[picked])
        _pusher()
        db.session.commit()
    rows = _daily_sheet(admin_client)
    assert (rows["Sita"]["present"], rows["Sita"]["holidays"], rows["Sita"]["earned"], rows["Sita"]["absent"]) == (3, 1, 2000, 11)
    assert (rows["Gita"]["present"], rows["Gita"]["holidays"], rows["Gita"]["earned"], rows["Gita"]["absent"]) == (3, 0, 1500, 12)
    assert _daily_sheet(admin_client, "2026-10-16")["Sita"]["holidays"] == 0               # only the day itself


def test_a_picked_holiday_they_worked_anyway_is_paid_once(app, admin_client):
    with app.app_context():
        w = _daily("Sita", "500", present=(1, 8))
        _holiday(date(2026, 10, 8), "Eid", workers=[w])
        _pusher()
        db.session.commit()
    row = _daily_sheet(admin_client)["Sita"]
    assert (row["present"], row["holidays"], row["earned"]) == (2, 0, 1000)


def test_the_days_list_shows_the_holiday_as_a_paid_day(app, admin_client):
    with app.app_context():
        w = _daily("Sita", "500", present=(1, 2))
        _holiday(date(2026, 10, 3), "Diwali", workers=[w])
        _pusher()
        db.session.commit()
        wid = w.id
    days = admin_client.get(f"/api/payroll/days?worker_id={wid}&start=2026-10-01&end=2026-10-05").get_json()["days"]
    by_day = {d["date"]: d for d in days}
    assert (by_day["2026-10-03"]["holiday"], by_day["2026-10-03"]["pay"], by_day["2026-10-03"]["present"]) == (True, 500.0, False)
    assert by_day["2026-10-01"]["holiday"] is False and by_day["2026-10-04"]["pay"] == 0.0


def test_a_picked_contractor_gets_it_too(app, admin_client):
    with app.app_context():
        w = _daily("Gita", "700", present=(1,), kind="contractor")
        _holiday(date(2026, 10, 2), "Diwali", workers=[w])
        _pusher()
        db.session.commit()
    assert _daily_sheet(admin_client)["Gita"]["earned"] == 1400


def test_the_daily_excel_has_a_paid_holidays_column(app, admin_client):
    import io

    from openpyxl import load_workbook
    with app.app_context():
        w = _daily("Sita", "500", present=(1,))
        _holiday(date(2026, 10, 2), "Diwali", workers=[w])
        _pusher()
        db.session.commit()
    ws = load_workbook(io.BytesIO(admin_client.get("/api/payroll/sheet/daily.xlsx?period=2026-10-01").data)).worksheets[0]
    header = [c.value for c in ws[2]]
    assert header[header.index("Absent days") + 1] == "Paid holidays"
    assert ws.cell(row=4, column=header.index("Paid holidays") + 1).value == 1


# ---------- leave and the register ----------

def test_a_holiday_is_not_counted_as_a_leave_day(app):
    with app.app_context():
        _holiday(date(2026, 10, 14))
        db.session.commit()
        days = working_days(date(2026, 10, 13), date(2026, 10, 16))
        assert days == [date(2026, 10, 13), date(2026, 10, 15), date(2026, 10, 16)]


def test_the_book_gives_a_salaried_employee_every_holiday_and_others_only_theirs(app):
    with app.app_context():
        picked = _daily("Sita")
        other = _daily("Gita")
        salaried = _salaried("Ravi", "30000")
        _holiday(date(2026, 10, 14), "Diwali", workers=[picked])
        _holiday(date(2026, 10, 20), "Eid")
        db.session.commit()
        book = HolidayBook(date(2026, 10, 1), date(2026, 10, 31))
        assert book.days(salaried) == {date(2026, 10, 14), date(2026, 10, 20)}
        assert book.days(picked) == {date(2026, 10, 14)} and book.days(other) == set()
        assert book.labels(salaried)[date(2026, 10, 14)] == "Diwali"
        assert book.days(salaried, date(2026, 10, 15), date(2026, 10, 31)) == {date(2026, 10, 20)}


def test_the_register_shows_the_holiday_instead_of_absent(app, admin_client):
    today = today_local()
    day = today - timedelta(days=1)
    with app.app_context():
        w = Worker(name="Sita", category="manpower", employment_type="daily_wages", wage_amount=Decimal("500"))
        db.session.add(w)
        db.session.flush()
        db.session.add(WorkerAttendance(worker=w, work_date=today - timedelta(days=4)))
        p = Worker(name="Zed Pusher", category="manpower")
        db.session.add(p)
        db.session.flush()
        db.session.add(WorkerAttendance(worker=p, work_date=today))
        _holiday(day, "Eid", workers=[w])
        db.session.commit()
        wid = w.id
    roster = admin_client.get("/api/workforce").get_json()
    person = next(r for key, rows in roster.items() if isinstance(rows, list) for r in rows if r["id"] == wid)
    status = {d["date"]: d["status"] for d in person["week"]}
    assert status[day.isoformat()] == "holiday" and status[(today - timedelta(days=2)).isoformat()] == "absent"
    record = admin_client.get(f"/api/workforce/{wid}").get_json()
    assert [(h["date"], h["name"]) for h in record["holidays"]] == [(day.isoformat(), "Eid")]


# ---------- the admin's screen ----------

def _declare(client, day="2026-12-25", name="Christmas", worker_ids=(), **extra):
    return client.post("/api/holidays", json={"date": day, "name": name, "worker_ids": list(worker_ids), **extra})


def test_the_admin_declares_changes_and_removes_a_holiday(app, admin_client):
    with app.app_context():
        sita = _daily("Sita")
        gita = _daily("Gita")
        db.session.commit()
        sid, gid = sita.id, gita.id
    r = _declare(admin_client, "2026-12-25", "Christmas", [sid])
    assert r.status_code == 201
    h = r.get_json()["holiday"]
    assert (h["date"], h["name"], h["worker_count"], [w["name"] for w in h["workers"]]) == ("2026-12-25", "Christmas", 1, ["Sita"])
    data = admin_client.get("/api/holidays").get_json()
    assert data["can_manage"] is True and [x["name"] for x in data["holidays"]] == ["Christmas"]
    assert [e["label"] for e in data["employees"]] == ["Gita", "Sita"]
    changed = admin_client.patch(f"/api/holidays/{h['id']}", json={"date": "2026-12-26", "name": "Boxing Day", "worker_ids": [gid]})
    assert changed.status_code == 200
    h2 = changed.get_json()["holiday"]
    assert (h2["date"], h2["name"], [w["name"] for w in h2["workers"]]) == ("2026-12-26", "Boxing Day", ["Gita"])
    with app.app_context():
        assert HolidayWorker.query.count() == 1
    assert admin_client.delete(f"/api/holidays/{h['id']}").status_code == 200
    assert admin_client.get("/api/holidays").get_json()["holidays"] == []
    assert admin_client.delete(f"/api/holidays/{h['id']}").status_code == 404
    with app.app_context():
        assert HolidayWorker.query.count() == 0


def test_what_cannot_be_declared_is_refused_and_nothing_is_saved(app, admin_client):
    with app.app_context():
        salaried = _salaried("Ravi", "30000")
        daily = _daily("Sita")
        db.session.commit()
        rid, did = salaried.id, daily.id
    far = (today_local() + timedelta(days=400)).isoformat()
    for kw, field in (({"day": "2026-09-30"}, "date"), ({"day": far}, "date"), ({"day": "soon"}, "date"), ({"day": ""}, "date"),
                      ({"name": "  "}, "name"), ({"name": "x" * 121}, "name"),
                      ({"worker_ids": [rid]}, "worker_ids"), ({"worker_ids": [99999]}, "worker_ids"), ({"worker_ids": "all"}, "worker_ids")):
        r = _declare(admin_client, **kw)
        assert r.status_code == 422 and field in r.get_json()["fields"], kw
    assert _declare(admin_client, "2026-12-25", "Christmas", [did]).status_code == 201
    twin = _declare(admin_client, "2026-12-25", " christmas ")
    assert twin.status_code == 422 and "name" in twin.get_json()["fields"]               # the same holiday twice
    assert _declare(admin_client, "2026-12-25", "Another").status_code == 201             # a different one on the same day is fine
    with app.app_context():
        assert Holiday.query.count() == 2


def test_only_the_admin_declares_but_others_can_look(app, admin_client, client, accounts_client, manager_client):
    with app.app_context():
        w = _daily("Sita")
        db.session.commit()
        wid = w.id
    hid = _declare(admin_client, "2026-12-25", "Christmas", [wid]).get_json()["holiday"]["id"]
    for c in (client, accounts_client, manager_client):
        assert _declare(c).status_code in (403, 404)
        assert c.patch(f"/api/holidays/{hid}", json={"date": "2026-12-26", "name": "x", "worker_ids": []}).status_code in (403, 404)
        assert c.delete(f"/api/holidays/{hid}").status_code in (403, 404)
    seen = manager_client.get("/api/holidays")
    if seen.status_code == 200:                                   # a reader sees the list, never who was picked, and cannot manage
        data = seen.get_json()
        assert data["can_manage"] is False and "employees" not in data and "workers" not in data["holidays"][0]
    with app.app_context():
        assert Holiday.query.count() == 1

"""Salary slips (kohal, 2026-11-10: "in payroll sheet, have a Release salary button. once clicked, it should show the same payroll sheet to the
employee the salary was released. also, have a vertical salary slip ... have them downloadable as well"). See app/slips.py and app/pdf.py."""

import re
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import SalarySlip, Worker, WorkerAttendance
from app.pdf import Page, build_pdf, string_width
from tests.conftest import make_user, signed_in


def _salaried(app, name="Ritesh", salary="31000", login=True, absent_days=()):
    """A salaried employee present every working day of October 2026 but `absent_days`; returns (their client or None, worker id)."""
    with app.app_context():
        user = make_user(name) if login else None
        w = Worker(name=name, category="staff", employment_type="regular", wage_amount=Decimal(salary), user_code=user.code if user else None)
        db.session.add(w)
        db.session.flush()
        for day in range(1, 32):
            if date(2026, 10, day).weekday() != 6 and day not in absent_days:
                db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
        db.session.commit()
        return (signed_in(app, user) if user else None), w.id


def _daily(app, name="Sita", rate="500", present=(1, 2, 3)):
    with app.app_context():
        user = make_user(name)
        w = Worker(name=name, category="manpower", employment_type="daily_wages", wage_amount=Decimal(rate), user_code=user.code)
        db.session.add(w)
        db.session.flush()
        for day in present:
            db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
        db.session.commit()
        return signed_in(app, user), w.id


def _pusher(app):
    """Attendance recorded on 1 Nov, so October's data is complete."""
    with app.app_context():
        p = Worker(name="Zed Pusher", category="manpower")
        db.session.add(p)
        db.session.flush()
        db.session.add(WorkerAttendance(worker=p, work_date=date(2026, 11, 1)))
        db.session.commit()


def _release(client, wid=None, kind="salaried", period="2026-10"):
    body = {"kind": kind, "period": period}
    if wid is not None:
        body["worker_id"] = wid
    return client.post("/api/payroll/slips", json=body)


def _sheet_row(client, wid, month="2026-10"):
    return next(r for r in client.get(f"/api/payroll/sheet?month={month}").get_json()["rows"] if r["id"] == wid)


def _valid_pdf(data):
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    start = int(re.search(rb"startxref\n(\d+)", data).group(1))
    assert data[start:start + 4] == b"xref"
    count = int(re.search(rb"xref\n0 (\d+)", data).group(1))
    entries = data[start:].split(b"\n")[2:2 + count]
    for number, entry in enumerate(entries[1:], start=1):                  # every object is where the table says it is
        assert data[int(entry[:10]):].startswith(f"{number} 0 obj".encode())


# ---------- the PDF writer ----------

def test_the_pdf_writer_makes_a_well_formed_file_and_escapes_text():
    page = Page()
    page.text(40, 800, "Name (with) a \\ slash and café ₹", size=12, bold=True)
    page.line(40, 790, 500, 790)
    page.rect(40, 700, 100, 30, fill=(0.9, 0.9, 0.9), stroke=(0, 0, 0))
    data = build_pdf([page], title="Test (title)")
    _valid_pdf(data)
    assert b"Name \\(with\\) a \\\\ slash and caf\xe9 ?" in data
    assert abs(string_width("1,000", 10) - 25.02) < 0.01


# ---------- releasing ----------

def test_releasing_a_salary_shows_the_employee_their_vertical_slip(app, admin_client):
    client, wid = _salaried(app, absent_days=(14,))
    _pusher(app)
    assert _sheet_row(admin_client, wid)["slip"] is None and _sheet_row(admin_client, wid)["has_login"] is True
    assert client.get("/api/salary-slips").get_json()["slips"] == []                       # nothing until it is released
    r = _release(admin_client, wid)
    assert r.status_code == 201 and r.get_json()["released"] == 1
    slip = _sheet_row(admin_client, wid)["slip"]
    assert slip["stale"] is False and slip["id"]
    listed = client.get("/api/salary-slips").get_json()["slips"]
    assert [(s["label"], s["net"], s["net_label"]) for s in listed] == [("October 2026", 30000, "Net pay")]
    view = client.get(f"/api/salary-slips/{listed[0]['id']}").get_json()["slip"]
    assert (view["name"], view["type_label"], view["from"], view["to"]) == ("Ritesh", "Salaried", "2026-10-01", "2026-10-31")
    assert [s["title"] for s in view["sections"]][:3] == ["Attendance", "Earnings", "Deductions"]
    rows = {row["label"]: row["value"] for s in view["sections"] for row in s["rows"]}
    assert rows["Absent days"] == 1 and rows["Month net salary"] == 30000 and rows["Monthly salary"] == 31000
    assert view["net"] == {"label": "Net pay", "value": 30000}


def test_the_slip_keeps_the_released_figures_and_the_sheet_says_when_it_changed(app, admin_client):
    client, wid = _salaried(app)
    _pusher(app)
    _release(admin_client, wid)
    with app.app_context():                                                                # a day of attendance is taken away afterwards
        db.session.delete(WorkerAttendance.query.filter_by(worker_id=wid, work_date=date(2026, 10, 14)).one())
        db.session.commit()
    assert _sheet_row(admin_client, wid)["net"] == 30000 and _sheet_row(admin_client, wid)["slip"]["stale"] is True
    sid = client.get("/api/salary-slips").get_json()["slips"][0]
    assert sid["net"] == 31000                                                             # the employee still sees what was released
    _release(admin_client, wid)                                                            # released again: the slip follows
    assert _sheet_row(admin_client, wid)["slip"]["stale"] is False
    assert client.get("/api/salary-slips").get_json()["slips"][0]["net"] == 30000
    with app.app_context():
        assert SalarySlip.query.count() == 1                                              # one slip per employee and period


def test_a_payment_made_after_release_does_not_count_as_a_change(app, admin_client):
    from app.models import WorkerPayment
    _, wid = _salaried(app)
    _pusher(app)
    _release(admin_client, wid)
    with app.app_context():
        db.session.add(WorkerPayment(worker_id=wid, label="Oct", amount=Decimal("10000"), paid_date=date(2026, 11, 3),
                                     period_start=date(2026, 10, 1), mode="CASH", position=1))
        db.session.commit()
    assert _sheet_row(admin_client, wid)["slip"]["stale"] is False


def test_release_all_releases_every_employee_on_the_sheet(app, admin_client):
    _, a = _salaried(app, "Ankush")
    _, b = _salaried(app, "Rashmi", login=False)
    _pusher(app)
    r = _release(admin_client)
    assert r.status_code == 201 and r.get_json()["released"] == 2
    assert _sheet_row(admin_client, a)["slip"] and _sheet_row(admin_client, b)["slip"]
    assert _sheet_row(admin_client, b)["has_login"] is False                              # the sheet can warn they cannot open it


def test_a_daily_wage_slip_for_a_pay_period(app, admin_client):
    client, wid = _daily(app, present=(1, 2, 3))
    _pusher(app)
    assert _release(admin_client, wid, "daily", "2026-10-01").status_code == 201
    slip = client.get("/api/salary-slips").get_json()["slips"][0]
    assert (slip["kind"], slip["label"], slip["net"], slip["net_label"]) == ("daily", "1–15 Oct 2026", 1500, "Net payable")
    view = client.get(f"/api/salary-slips/{slip['id']}").get_json()["slip"]
    rows = {row["label"]: row["value"] for s in view["sections"] for row in s["rows"]}
    assert (view["type_label"], rows["Present days"], rows["Wages earned"], rows["Daily wage"]) == ("Daily wages", 3, 1500, 500)
    daily_row = next(r for r in admin_client.get("/api/payroll/sheet/daily?period=2026-10-01").get_json()["rows"] if r["id"] == wid)
    assert daily_row["slip"]["id"] == slip["id"]


def test_withdrawing_takes_the_slip_away_from_the_employee(app, admin_client):
    client, wid = _salaried(app)
    _pusher(app)
    _release(admin_client, wid)
    sid = _sheet_row(admin_client, wid)["slip"]["id"]
    assert admin_client.delete(f"/api/payroll/slips/{sid}").status_code == 200
    assert client.get("/api/salary-slips").get_json()["slips"] == [] and client.get(f"/api/salary-slips/{sid}").status_code == 404
    assert _sheet_row(admin_client, wid)["slip"] is None
    assert admin_client.delete(f"/api/payroll/slips/{sid}").status_code == 404


def test_an_employee_sees_only_their_own_slip_and_the_admin_sees_any(app, admin_client):
    mine, a = _salaried(app, "Ankush")
    other, b = _salaried(app, "Rashmi")
    _pusher(app)
    _release(admin_client)
    sid_a = mine.get("/api/salary-slips").get_json()["slips"][0]["id"]
    sid_b = other.get("/api/salary-slips").get_json()["slips"][0]["id"]
    assert [s["id"] for s in mine.get("/api/salary-slips").get_json()["slips"]] == [sid_a]
    assert mine.get(f"/api/salary-slips/{sid_b}").status_code == 404 and mine.get(f"/api/salary-slips/{sid_b}.pdf").status_code == 404
    assert admin_client.get(f"/api/salary-slips/{sid_b}").status_code == 200 and admin_client.get(f"/api/salary-slips/{sid_b}.pdf").status_code == 200


def test_the_slip_downloads_as_a_pdf(app, admin_client):
    client, wid = _salaried(app, "Ritesh Kumar", salary="31000", absent_days=(14,))
    _pusher(app)
    _release(admin_client, wid)
    sid = client.get("/api/salary-slips").get_json()["slips"][0]["id"]
    res = client.get(f"/api/salary-slips/{sid}.pdf")
    assert res.status_code == 200 and res.mimetype == "application/pdf"
    assert 'filename="salary-slip-ritesh-kumar-october-2026.pdf"' in res.headers["Content-Disposition"]
    _valid_pdf(res.data)
    for text in (b"SALARY SLIP", b"October 2026", b"Ritesh Kumar", b"Net pay", b"Rs. 30,000", rb"Present days \(paid days\)", b"Released on"):
        assert text in res.data, text


def test_the_admin_can_download_any_rows_slip_before_releasing_it(app, admin_client, client):
    _, wid = _salaried(app, "Ritesh")
    _pusher(app)
    res = admin_client.get(f"/api/payroll/slips/pdf?kind=salaried&period=2026-10&worker_id={wid}")
    assert res.status_code == 200 and b"Ritesh" in res.data and b"Rs. 31,000" in res.data
    _valid_pdf(res.data)
    with app.app_context():
        assert SalarySlip.query.count() == 0                                              # a preview releases nothing
    assert client.get(f"/api/payroll/slips/pdf?kind=salaried&period=2026-10&worker_id={wid}").status_code in (403, 404)


def test_only_the_admin_releases_and_what_cannot_be_released_is_refused(app, admin_client, client, manager_client, accounts_client):
    _, wid = _salaried(app)
    _pusher(app)
    for c in (client, manager_client, accounts_client):
        assert _release(c, wid).status_code in (403, 404)
    for kw in ({"kind": "yearly", "period": "2026-10"}, {"kind": "salaried", "period": "2026-09"}, {"kind": "salaried", "period": "2099-01"},
               {"kind": "salaried", "period": "soon"}, {"kind": "daily", "period": "2026-10-05"}, {"kind": "daily", "period": "2026-09-16"},
               {"kind": "salaried", "period": "2026-10", "worker_id": "x"}):
        assert admin_client.post("/api/payroll/slips", json=kw).status_code == 422, kw
    assert _release(admin_client, 99999).status_code == 422                                # no row for them: nothing to release
    with app.app_context():
        assert SalarySlip.query.count() == 0


def test_the_me_hub_offers_a_salaried_employee_their_slips(app, admin_client):
    client, wid = _salaried(app)
    _pusher(app)
    assert b"Salary slips" in client.get("/me").data
    assert client.get("/salary-slips").status_code == 200
    anyone = signed_in(app, make_user("Nobody Special"))
    assert b"Salary slips" not in anyone.get("/me").data                                   # no employee record, nothing to show


def test_deleting_the_employee_removes_their_slips(app, admin_client):
    _, wid = _salaried(app)
    _pusher(app)
    _release(admin_client, wid)
    with app.app_context():
        db.session.delete(db.session.get(Worker, wid))
        db.session.commit()
        assert SalarySlip.query.count() == 0

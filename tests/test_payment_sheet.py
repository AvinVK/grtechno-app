"""The monthly payment sheet (kohal, 2026-11-08: "this is now the payslip is suppose to look, is it possible to show in the app and
then have excel downloadable?") and the salary rule that came with it: salary cut for absences ("Cut for absences"), plus a fixed
house rent / petrol amount per employee ("Fixed per employee"). See app/payroll.py's salaried_month / payment_sheet."""

import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from openpyxl import load_workbook

from app.extensions import db
from app.models import SalaryAdvance, Worker, WorkerAttendance, WorkerPayment


def _salaried(name, salary, allowance=None, absent_days=(), present=True):
    """A salaried employee present every working day of October 2026 except `absent_days` (or no attendance at all)."""
    w = Worker(name=name, category="staff", employment_type="regular", wage_amount=Decimal(salary),
               allowance_amount=Decimal(allowance) if allowance else None)
    db.session.add(w)
    db.session.flush()
    if present:
        for day in range(1, 32):
            if date(2026, 10, day).weekday() != 6 and day not in absent_days:
                db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
    return w


def _pusher():
    """Attendance recorded on 1 Nov, so October's data is complete."""
    p = Worker(name="Zed Pusher", category="manpower")
    db.session.add(p)
    db.session.flush()
    db.session.add(WorkerAttendance(worker=p, work_date=date(2026, 11, 1)))


def _sheet(client, month="2026-10"):
    return client.get(f"/api/payroll/sheet?month={month}").get_json()


def _row(data, name):
    return next(r for r in data["rows"] if r["name"] == name)


def test_a_full_month_pays_the_full_salary_and_absences_are_cut_at_the_rupee_day_rate(app, admin_client):
    with app.app_context():
        _salaried("Ankush", "15000", allowance="1000")
        _salaried("Rashmi", "15000", absent_days=(6, 7, 8, 9))         # four working days missed
        _salaried("Ritesh", "27500", absent_days=(20,))
        _pusher()
        db.session.commit()
    data = _sheet(admin_client)
    assert data["label"] == "October 2026" and not data["in_progress"]
    ankush = _row(data, "Ankush")
    # as on kohal's sheet: 15,000 / 31 = 484 a day; 31 present, nothing cut, 1,000 house rent on top
    assert (ankush["per_day"], ankush["present"], ankush["absent"], ankush["net"], ankush["allowance"], ankush["gross"]) == (
        484, 31, 0, 15000, 1000, 16000)
    rashmi = _row(data, "Rashmi")
    assert (rashmi["present"], rashmi["absent"], rashmi["net"], rashmi["deduction"]) == (27, 4, 13068, 1932)    # 484 x 27
    ritesh = _row(data, "Ritesh")
    assert (ritesh["per_day"], ritesh["present"], ritesh["net"]) == (887, 30, 26610)                           # 887 x 30
    assert data["totals"]["gross"] == 16000 + 13068 + 26610
    assert [r["name"] for r in data["rows"]] == ["Ankush", "Rashmi", "Ritesh"]       # salaried only, name order


def test_sundays_are_never_absences(app, admin_client):
    with app.app_context():
        w = _salaried("Sunny", "31000")
        # also present on a Sunday: still 31 days, never more
        db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, 4)))
        _pusher()
        db.session.commit()
    sunny = _row(_sheet(admin_client), "Sunny")
    assert (sunny["present"], sunny["absent"], sunny["net"]) == (31, 0, 31000)


def test_the_advance_columns(app, admin_client):
    with app.app_context():
        w = _salaried("Ritesh", "31000")
        db.session.add(SalaryAdvance(worker=w, amount=Decimal("6000"), months=2, first_month=date(2026, 10, 1),
                                     given_date=date(2026, 10, 5), payment_account="CASH"))
        _pusher()
        db.session.commit()
    october = _row(_sheet(admin_client), "Ritesh")
    assert (october["old_advance"], october["advance_taken"], october["advance_total"], october["advance_deduction"],
            october["advance_balance"]) == (0, 6000, 6000, 3000, 3000)
    assert october["gross"] == 31000 - 3000
    november = _row(_sheet(admin_client, "2026-11"), "Ritesh")
    assert (november["old_advance"], november["advance_taken"], november["advance_deduction"], november["advance_balance"]) == (
        3000, 0, 3000, 0)


def test_paid_counts_payments_marked_for_the_month_and_unmarked_ones_paid_in_it(app, admin_client):
    with app.app_context():
        w = _salaried("Ankush", "31000")
        db.session.add_all([
            WorkerPayment(worker=w, label="October salary", amount=Decimal("20000"), paid_date=date(2026, 11, 3),
                          period_start=date(2026, 10, 1), mode="CASH", position=1),
            WorkerPayment(worker=w, label="Part", amount=Decimal("5000"), paid_date=date(2026, 10, 20), mode="CASH", position=2),
            WorkerPayment(worker=w, label="Not paid yet", amount=Decimal("999"), mode="CASH", position=3),
        ])
        _pusher()
        db.session.commit()
    ankush = _row(_sheet(admin_client), "Ankush")
    assert ankush["paid"] == 25000 and ankush["salary_due"] == 31000 - 25000
    assert _row(_sheet(admin_client, "2026-11"), "Ankush")["paid"] == 0          # the November payment was for October


def test_someone_with_no_attendance_at_all_is_flagged(app, admin_client):
    with app.app_context():
        _salaried("Ghost", "31000", present=False)
        _salaried("Ankush", "31000")
        _pusher()
        db.session.commit()
    data = _sheet(admin_client)
    assert _row(data, "Ghost")["no_attendance"] is True and _row(data, "Ghost")["absent"] == 27
    assert _row(data, "Ankush")["no_attendance"] is False


def test_payroll_due_follows_the_same_rule(app, admin_client):
    with app.app_context():
        w = _salaried("Rashmi", "15000", allowance="500", absent_days=(6, 7, 8, 9))
        _pusher()
        db.session.commit()
        wid = w.id
    row = next(e for e in admin_client.get("/api/payroll/overview").get_json()["employees"] if e["id"] == wid)
    sheet_oct = _row(_sheet(admin_client), "Rashmi")
    sheet_nov = _row(_sheet(admin_client, "2026-11"), "Rashmi")
    # October (cut) and the month so far, each with the 500 house rent
    assert row["earned"] == round(sheet_oct["net"] + 500 + sheet_nov["net"] + 500, 2)


def test_the_excel_file_is_laid_out_like_the_sheet(app, admin_client):
    with app.app_context():
        _salaried("Ankush", "15000", allowance="1000")
        _pusher()
        db.session.commit()
    res = admin_client.get("/api/payroll/sheet.xlsx?month=2026-10")
    assert res.status_code == 200 and "payment-sheet-2026-10.xlsx" in res.headers["Content-Disposition"]
    wb = load_workbook(io.BytesIO(res.data))
    ws = wb["October 2026"]
    assert ws["A1"].value == "PAYMENT SHEET OF October 2026"
    merged = {str(m) for m in ws.merged_cells.ranges}
    assert {"A1:Y1", "C2:D2", "A2:A3", "B2:B3", "Y2:Y3"} <= merged
    assert (ws["C2"].value, ws["C3"].value, ws["D3"].value) == ("Work Days", "From", "To")
    row = [c.value for c in ws[4]]
    assert row[0] == 1 and row[1] == "Ankush" and row[2].date() == date(2026, 10, 1) and row[4] == 15000 and row[23] == 16000
    assert (ws["J2"].value, ws["K2"].value, ws["L2"].value, ws["M2"].value) == ("Sick leave", "Casual leave", "Sick leave balance", "Casual leave balance")
    assert ws.cell(row=5, column=2).value == "Total"
    assert ws["B4"].border.left.style == "thin"
    with zipfile.ZipFile(io.BytesIO(res.data)) as z:                  # the header wraps
        assert 'wrapText="1"' in z.read("xl/styles.xml").decode()


def test_only_months_payroll_covers_and_only_with_payroll_access(app, admin_client, client):
    assert admin_client.get("/api/payroll/sheet?month=2026-09").status_code == 422     # before payroll's 1 Oct start
    assert admin_client.get("/api/payroll/sheet?month=2099-01").status_code == 422
    assert admin_client.get("/api/payroll/sheet?month=nope").status_code == 422
    data = admin_client.get("/api/payroll/sheet").get_json()                            # this month by default
    assert data["months"][-1]["value"] == "2026-10" and data["month"] == data["months"][0]["value"]
    assert client.get("/api/payroll/sheet").status_code in (403, 404)
    assert client.get("/api/payroll/sheet.xlsx").status_code in (403, 404)


def test_the_house_rent_is_saved_on_the_employee(app, admin_client):
    with app.app_context():
        w = Worker(name="Deepak", category="staff", employment_type="regular", wage_amount=Decimal("16940"))
        db.session.add(w)
        db.session.commit()
        wid = w.id
    assert admin_client.patch(f"/api/workforce/{wid}", json={"allowance_amount": "3000"}).status_code == 200
    assert admin_client.get(f"/api/workforce/{wid}").get_json()["worker"]["allowance_amount"] == 3000.0
    assert admin_client.patch(f"/api/workforce/{wid}", json={"allowance_amount": "abc"}).status_code == 422
    assert admin_client.patch(f"/api/workforce/{wid}", json={"allowance_amount": ""}).status_code == 200
    assert admin_client.get(f"/api/workforce/{wid}").get_json()["worker"]["allowance_amount"] is None


def test_the_sheet_and_the_excel_file_can_be_cut_to_one_employee(app, admin_client):
    """kohal, 2026-11-08: "give filter to select the employee"."""
    with app.app_context():
        ankush = _salaried("Ankush", "15000", allowance="1000")
        _salaried("Rashmi", "15000", absent_days=(6, 7, 8, 9))
        _pusher()
        db.session.commit()
        aid = ankush.id
    data = admin_client.get(f"/api/payroll/sheet?month=2026-10&worker_id={aid}").get_json()
    assert [r["name"] for r in data["rows"]] == ["Ankush"] and data["totals"]["gross"] == 16000
    assert [e["label"] for e in data["employees"]] == ["Ankush", "Rashmi"]                  # everyone can still be picked
    res = admin_client.get(f"/api/payroll/sheet.xlsx?month=2026-10&worker_id={aid}")
    assert "payment-sheet-2026-10-ankush.xlsx" in res.headers["Content-Disposition"]
    ws = load_workbook(io.BytesIO(res.data))["October 2026"]
    assert ws["B4"].value == "Ankush" and ws["B5"].value == "Total"



def test_the_day_toggle_on_the_attendance_record_changes_the_salary(app, admin_client):
    """kohal, 2026-11-08: "does marking present/absent also affects the salary? it should"."""
    with app.app_context():
        w = _salaried("Ritesh", "31000")                         # present every working day of October
        _pusher()
        db.session.commit()
        wid = w.id
    assert _row(_sheet(admin_client), "Ritesh")["net"] == 31000
    off = admin_client.post("/api/attendance/manual/day", json={"worker_id": wid, "work_date": "2026-10-14", "present": False})
    assert off.status_code == 200
    row = _row(_sheet(admin_client), "Ritesh")
    assert (row["absent"], row["net"]) == (1, 1000 * 30)                                    # 31,000 / 31 = 1,000 a day
    admin_client.post("/api/attendance/manual/day", json={"worker_id": wid, "work_date": "2026-10-14", "present": True})
    assert _row(_sheet(admin_client), "Ritesh")["net"] == 31000



# ---------- daily wages (kohal, 2026-11-09) ----------
#
# "need to do the same payroll features and everything what u did for salaried employee with daily wages as well. no sick leave
# casual leave for daily wages, no sunday off as well. they work, they get paid bi-weekly."

def _daily(name, rate="500", present=(), kind="daily_wages"):
    w = Worker(name=name, category="manpower", employment_type=kind, wage_amount=Decimal(rate))
    db.session.add(w)
    db.session.flush()
    for day in present:
        db.session.add(WorkerAttendance(worker=w, work_date=date(2026, 10, day)))
    return w


def _daily_sheet(client, period="2026-10-01", **extra):
    query = "&".join([f"period={period}"] + [f"{k}={v}" for k, v in extra.items()])
    return client.get(f"/api/payroll/sheet/daily?{query}").get_json()


def test_daily_wages_are_paid_for_the_days_worked_and_sundays_are_not_a_day_off(app, admin_client):
    with app.app_context():
        _daily("Sita", "500", present=(3, 4, 5))                 # Sat 3rd, Sun 4th, Mon 5th
        _pusher()
        db.session.commit()
    row = _row(_daily_sheet(admin_client), "Sita")
    assert (row["present"], row["earned"]) == (3, 1500)                                   # the Sunday worked is paid like any other day
    assert row["absent"] == 12 and row["days_in_period"] == 15                              # 15 days less 3 worked - Sundays included
    second = _row(_daily_sheet(admin_client, "2026-10-16"), "Sita")
    assert (second["present"], second["earned"], second["absent"]) == (0, 0, 16)           # no credit for the Sundays not worked
    assert second["no_attendance"] is True


def test_the_daily_sheet_has_the_advance_and_paid_columns(app, admin_client):
    with app.app_context():
        w = _daily("Gita", "500", present=(1, 2, 3, 6, 7, 8, 9, 10), kind="contractor")        # 8 days = 4,000
        db.session.add(SalaryAdvance(worker=w, amount=Decimal("3000"), months=2, first_month=date(2026, 10, 1),
                                     given_date=date(2026, 10, 5), payment_account="CASH"))
        db.session.add(WorkerPayment(worker=w, label="First half", amount=Decimal("700"), paid_date=date(2026, 10, 17),
                                     period_start=date(2026, 10, 1), mode="CASH", position=1))
        _pusher()
        db.session.commit()
    first = _row(_daily_sheet(admin_client), "Gita")
    # 1,500 a month taken back, half in each period: 750 now
    assert (first["old_advance"], first["advance_taken"], first["advance_deduction"], first["advance_balance"]) == (0, 3000, 750, 2250)
    assert (first["earned"], first["net"], first["paid"], first["due"]) == (4000, 3250, 700, 2550)
    second = _row(_daily_sheet(admin_client, "2026-10-16"), "Gita")
    assert (second["old_advance"], second["advance_taken"], second["advance_deduction"], second["advance_balance"]) == (2250, 0, 750, 1500)
    assert second["net"] == -750 and second["due"] == -750                                   # nothing worked, so the advance is owed back
    assert _daily_sheet(admin_client)["totals"]["earned"] == 4000


def test_the_daily_sheet_is_for_day_rate_staff_only_and_salaried_staff_stay_on_theirs(app, admin_client):
    with app.app_context():
        _daily("Sita", present=(5,))
        _salaried("Ravi", "31000")
        _pusher()
        db.session.commit()
    assert [r["name"] for r in _daily_sheet(admin_client)["rows"]] == ["Sita"]
    assert "Sita" not in [r["name"] for r in _sheet(admin_client)["rows"]]


def test_the_daily_sheet_filter_periods_and_excel(app, admin_client):
    with app.app_context():
        sita = _daily("Sita Devi", "500", present=(1, 2))
        _daily("Gita", "600", present=(3,))
        _pusher()
        db.session.commit()
        sid = sita.id
    data = _daily_sheet(admin_client, worker_id=sid)
    assert [r["name"] for r in data["rows"]] == ["Sita Devi"] and data["totals"]["earned"] == 1000
    assert [e["label"] for e in data["employees"]] == ["Gita", "Sita Devi"]
    assert data["periods"][-1] == {"value": "2026-10-01", "label": "1–15 Oct 2026"}
    assert data["periods"][0]["value"] in (date.today().replace(day=1).isoformat(), date.today().replace(day=16).isoformat())
    res = admin_client.get(f"/api/payroll/sheet/daily.xlsx?period=2026-10-01&worker_id={sid}")
    assert res.status_code == 200 and "daily-wages-sheet-2026-10-01-sita-devi.xlsx" in res.headers["Content-Disposition"]
    ws = load_workbook(io.BytesIO(res.data)).worksheets[0]
    assert ws["A1"].value == "PAYMENT SHEET OF DAILY WAGES 1–15 Oct 2026" and "A1:R1" in {str(m) for m in ws.merged_cells.ranges}
    assert [c.value for c in ws[4]][:9] == [1, "Sita Devi", ws["C4"].value, ws["D4"].value, 500, 15, 2, 13, 1000]
    assert ws["B5"].value == "Total"
    for bad in ("2026-09-16", "2026-10-05", "soon", "2099-01-01"):
        assert admin_client.get(f"/api/payroll/sheet/daily?period={bad}").status_code == 422, bad


def test_the_daily_sheet_is_for_payroll_access_only(app, client):
    assert client.get("/api/payroll/sheet/daily").status_code in (403, 404)
    assert client.get("/api/payroll/sheet/daily.xlsx").status_code in (403, 404)


def test_attendance_screens_treat_sunday_as_a_working_day_for_daily_wages(app, admin_client):
    from conftest import make_user, signed_in
    today = date.today()
    with app.app_context():
        daily_user, salaried_user = make_user("Daily Person"), make_user("Salaried Person")
        d = Worker(name="Daily Person", category="manpower", employment_type="daily_wages", wage_amount=Decimal("500"),
                   user_code=daily_user.code, first_seen=today - timedelta(days=60))
        s = Worker(name="Salaried Person", category="staff", employment_type="regular", wage_amount=Decimal("30000"),
                   user_code=salaried_user.code, first_seen=today - timedelta(days=60))
        db.session.add_all([d, s])
        db.session.flush()
        for w in (d, s):
            db.session.add(WorkerAttendance(worker=w, work_date=today))
        db.session.commit()
        daily_client, salaried_client = signed_in(app, daily_user), signed_in(app, salaried_user)
    assert daily_client.get("/api/attendance/state").get_json()["works_sundays"] is True
    assert salaried_client.get("/api/attendance/state").get_json()["works_sundays"] is False
    register = admin_client.get("/api/workforce").get_json()
    people = {p["name"]: p for k, v in register.items() if isinstance(v, list) for p in v}
    def sunday_status(name):
        return next(day["status"] for day in people[name]["week"] if date.fromisoformat(day["date"]).weekday() == 6)
    if today.weekday() != 6:                                  # on a Sunday itself both are present today
        assert sunday_status("Daily Person") == "absent" and sunday_status("Salaried Person") == "off"

"""Running today (kohal, 2026-11-06) - a project is running on a day when someone's attendance is recorded against it that day."""

from datetime import timedelta

from app.extensions import db
from app.models import Attendance, Client, Project, Worker, WorkerAttendance, utcnow
from app.timeutil import today_local

from conftest import make_user


def _projects(app):
    """Plant A (someone checks in today), Plant B (only a past day), Plant C (an employee marked present today), Plant D (nobody)."""
    with app.app_context():
        c = Client(name="Acme")
        db.session.add(c)
        db.session.flush()
        ps = [Project(client=c, title=t, status="running") for t in ("Plant A", "Plant B", "Plant C", "Plant D")]
        db.session.add_all(ps)
        db.session.commit()
        return [p.id for p in ps]


def _check_in(app, user_name, project_id, day=None, status="approved"):
    with app.app_context():
        u = make_user(user_name)
        db.session.add(Attendance(user_code=u.code, work_date=day or today_local(), project_id=project_id, check_in_at=utcnow(), status=status))
        db.session.commit()
        return u.code


def test_a_project_runs_today_when_attendance_is_recorded_against_it(app, admin_client):
    a, b, c, d = _projects(app)
    _check_in(app, "Ravi", a)
    _check_in(app, "Old Timer", b, day=today_local() - timedelta(days=1))                     # yesterday only: not running today
    with app.app_context():
        w = Worker(name="Sita Helper", category="manpower")
        db.session.add(w)
        db.session.flush()
        db.session.add(WorkerAttendance(worker_id=w.id, work_date=today_local(), status="present", project_id=c))
        db.session.commit()
    data = admin_client.get("/api/projects/running-today").get_json()
    assert data["date"] == today_local().isoformat()
    assert {p["title"]: [x["name"] for x in p["on_site"]] for p in data["projects"]} == {"Plant A": ["Ravi"], "Plant C": ["Sita Helper"]}


def test_pending_counts_as_on_site_but_says_so_and_rejected_does_not(app, admin_client):
    a, b, _, _ = _projects(app)
    _check_in(app, "Ravi", a)
    _check_in(app, "Waiting", a, status="pending")
    _check_in(app, "Turned Away", b, status="rejected")
    data = admin_client.get("/api/projects/running-today").get_json()
    assert [p["title"] for p in data["projects"]] == ["Plant A"]
    assert {x["name"]: x["pending"] for x in data["projects"][0]["on_site"]} == {"Ravi": False, "Waiting": True}


def test_an_employee_with_a_login_is_counted_once(app, admin_client):
    a, _, _, _ = _projects(app)
    code = _check_in(app, "Ravi", a)
    with app.app_context():
        w = Worker(name="Ravi", category="manpower", user_code=code)
        db.session.add(w)
        db.session.flush()
        db.session.add(WorkerAttendance(worker_id=w.id, work_date=today_local(), status="present", project_id=a))
        db.session.commit()
    data = admin_client.get("/api/projects/running-today").get_json()
    assert [x["name"] for x in data["projects"][0]["on_site"]] == ["Ravi"]


def test_the_admin_project_managers_and_accountant_see_it_and_nobody_else(app, admin_client, manager_client, accounts_client, client):
    a, *_ = _projects(app)
    _check_in(app, "Ravi", a)
    for c in (admin_client, manager_client, accounts_client):
        assert [p["title"] for p in c.get("/api/projects/running-today").get_json()["projects"]] == ["Plant A"]
        assert c.get("/api/projects").get_json()["can_see_running"] is True
    assert client.get("/api/projects/running-today").status_code in (403, 404)               # a sales person has no such tab
    assert client.get("/api/projects").status_code in (200, 403) and (client.get("/api/projects").status_code == 403
                                                                      or client.get("/api/projects").get_json()["can_see_running"] is False)


def test_a_chandrapur_manager_only_sees_running_projects_they_may_see(app):
    from app.constants import COMMISSION_ROLE_KEY
    from app.models import Role, RoleModule
    from conftest import signed_in
    a, b, _, _ = _projects(app)
    _check_in(app, "Ravi", a)
    _check_in(app, "Sunil", b)
    with app.app_context():
        db.session.add(Role(key=COMMISSION_ROLE_KEY, name="Project manager Chandrapur"))      # a custom role on prod, not in the seed
        db.session.add(RoleModule(role_key=COMMISSION_ROLE_KEY, module_key="projects"))       # its Projects access, set on prod by the admin
        db.session.commit()
        pm = make_user("Chandrakant", role=COMMISSION_ROLE_KEY)
        db.session.get(Project, a).site_district = "Chandrapur"
        db.session.commit()
        pm_client = signed_in(app, pm)
    titles = [p["title"] for p in pm_client.get("/api/projects/running-today").get_json()["projects"]]
    assert titles == ["Plant A"]                                                              # Plant B is outside their district

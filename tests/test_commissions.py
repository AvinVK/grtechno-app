"""Commission: a Project manager Chandrapur's own read-only view of what they've earned (kohal,
2026-10-18: "now this guy has to see his comissions, how does he check that?"). See app/commissions.py and
test_workforce.py's own commission_total tests for the admin-side equivalent this mirrors."""

from datetime import date
from decimal import Decimal

from app.constants import COMMISSION_ROLE_KEY
from app.extensions import db
from app.models import Client, Project, ProjectExpense, Role, Worker
from conftest import make_user, signed_in


def chandrapur_pm_with_commissions(app, name="Chetan Chandrapur"):
    """A signed-in User with a matching Worker in the commission role, and two commission entries against
    two different projects - same shape as test_workforce.py's own setup for the admin-side popup."""
    if db.session.get(Role, COMMISSION_ROLE_KEY) is None:
        db.session.add(Role(key=COMMISSION_ROLE_KEY, name="Project manager Chandrapur", sees_all=False))
        db.session.flush()
    user = make_user(name, pin="285193")
    worker = Worker(name=name, category="staff", role_key=COMMISSION_ROLE_KEY, user_code=user.code)
    db.session.add(worker)
    c1, c2 = Client(name="Site A"), Client(name="Site B")
    db.session.add_all([c1, c2])
    db.session.flush()
    p1 = Project(client=c1, title="Site A job", estimated_amount=200000)
    p2 = Project(client=c2, title="Site B job", estimated_amount=500000)
    db.session.add_all([p1, p2])
    db.session.flush()
    db.session.add_all([
        ProjectExpense(project=p1, worker=worker, kind="commission", percent=Decimal("5"), basis_amount=Decimal("200000"),
                        amount=Decimal("10000"), entry_date=date.today()),
        ProjectExpense(project=p2, worker=worker, kind="commission", percent=Decimal("2"), basis_amount=Decimal("500000"),
                        amount=Decimal("10000"), entry_date=date.today()),
    ])
    db.session.commit()
    return signed_in(app, user), worker


def test_commissions_page_needs_the_chandrapur_role(client, admin_client):
    assert client.get("/commissions").status_code == 403       # plain user, not that role
    assert client.get("/api/commissions/me").status_code == 403
    assert admin_client.get("/commissions").status_code == 403  # the admin has no Worker row at all


def test_a_chandrapur_pm_sees_their_own_total_and_breakdown(app):
    pm, worker = chandrapur_pm_with_commissions(app)
    assert pm.get("/commissions").status_code == 200
    data = pm.get("/api/commissions/me").get_json()
    assert data["commission_total"] == 20000.0
    by_project = {c["project_title"]: c["percent"] for c in data["commissions"]}
    assert by_project == {"Site A job": 5.0, "Site B job": 2.0}
    assert all(c["amount"] == 10000.0 for c in data["commissions"])


def test_a_chandrapur_pm_with_no_commission_yet_sees_zero_not_an_error(app):
    if db.session.get(Role, COMMISSION_ROLE_KEY) is None:
        db.session.add(Role(key=COMMISSION_ROLE_KEY, name="Project manager Chandrapur", sees_all=False))
        db.session.flush()
    user = make_user("Fresh Chandrapur", pin="285193")
    worker = Worker(name="Fresh Chandrapur", category="staff", role_key=COMMISSION_ROLE_KEY, user_code=user.code)
    db.session.add(worker)
    db.session.commit()
    pm = signed_in(app, user)
    data = pm.get("/api/commissions/me").get_json()
    assert data["commission_total"] == 0.0 and data["commissions"] == []


def test_a_worker_in_a_different_role_cannot_see_this_page(app):
    user = make_user("Wendy Welder", pin="285193", role="welder")
    worker = Worker(name="Wendy Welder", category="manpower", role_key="welder", user_code=user.code)
    db.session.add(worker)
    db.session.commit()
    who = signed_in(app, user)
    assert who.get("/commissions").status_code == 403
    assert who.get("/api/commissions/me").status_code == 403


def test_the_me_hub_shows_a_commission_tile_with_the_total(app):
    pm, worker = chandrapur_pm_with_commissions(app)
    html = pm.get("/me").get_data(as_text=True)
    assert "Commission</span>" in html and 'href="/commissions"' in html
    assert "20000" in html or "20,000" in html

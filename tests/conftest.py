import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.auth import create_user
from app.config import Config
from app.extensions import db
from app import reference_data as ref
from app.models import Module, Role, RoleModule, SiteCategory

PIN = "482915"


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret-not-a-placeholder-key"


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        seed_reference_data()
        yield app
        db.session.remove()
        db.drop_all()


def seed_reference_data():
    """What the migrations put in a real database: services, roles, who can open what, site categories."""
    db.session.add(Module(key="leads", name="Leads", icon="leads", path="/", sort_order=1))
    for key, name, icon, path, order in ref.NEW_MODULES:
        db.session.add(Module(key=key, name=name, icon=icon, path=path, sort_order=order))
    for key, name, sees_all in ref.ROLES:
        db.session.add(Role(key=key, name=name, sees_all=sees_all))
    db.session.flush()
    for role, keys in ref.ROLE_MODULES.items():
        for module in keys:
            db.session.add(RoleModule(role_key=role, module_key=module))
    for i, name in enumerate(ref.SITE_CATEGORIES, start=1):
        db.session.add(SiteCategory(name=name, sort_order=i))
    db.session.commit()


def make_user(name, is_admin=False, pin=PIN, role=None):
    """A user who has already set their PIN."""
    user, _ = create_user(name, is_admin=is_admin, role=role)
    user.password_hash = generate_password_hash(pin)
    user.setup_code_hash = None
    user.setup_code_expires = None
    db.session.commit()
    return user


def signed_in(app, user):
    client = app.test_client()
    with client.session_transaction() as s:
        s["uid"] = user.code
    return client


def csrf(client):
    """A CSRF token for this client's session (works signed in or out)."""
    client.get("/login")
    with client.session_transaction() as s:
        has_token = "csrf" in s
    if not has_token:                            # signed in: /login redirected, so load a page that has a form
        client.get("/me")
    with client.session_transaction() as s:
        return s["csrf"]


@pytest.fixture
def user(app):
    return make_user("Tester")


@pytest.fixture
def admin(app):
    return make_user("grtechno", is_admin=True)


@pytest.fixture
def client(app, user):
    return signed_in(app, user)


@pytest.fixture
def admin_client(app, admin):
    return signed_in(app, admin)


@pytest.fixture
def manager(app):
    return make_user("Priya Manager", role="project_manager")


@pytest.fixture
def manager_client(app, manager):
    return signed_in(app, manager)


@pytest.fixture
def accounts(app):
    return make_user("Anil Accounts", role="accounts")


@pytest.fixture
def accounts_client(app, accounts):
    return signed_in(app, accounts)


@pytest.fixture
def anon(app):
    return app.test_client()


def advance_to_negotiation(client, lead_id):
    """Drive a lead from New enquiry through a finalized negotiation round - survey done, quote sent, one
    finalized round. Shared setup for stage-gate tests and win_lead below. Doesn't touch est_value (a
    caller may have set its own) - a project's amount comes from the latest round, not est_value, see
    test_negotiation_rounds_added_edited_and_used_as_the_project_estimate. The round's own estimate
    matches the 1,000,000 most callers' leads already use for est_value, so totals stay compatible."""
    client.put(f"/api/leads/{lead_id}/survey", json={
        "survey_date": "2026-09-20", "site_category": "Commercial complex", "site_pincode": "411001",
        "site_state": "Maharashtra", "site_district": "Pune", "site_city": "Pune City", "site_address": "Plot 12, MIDC",
    })
    client.patch(f"/api/leads/{lead_id}", json={"quote_sent_date": "2026-09-21"})
    client.post(f"/api/leads/{lead_id}/negotiations", json={
        "date": "2026-09-22", "authorized_person": "Mr. Rao", "estimate": 1000000, "finalized": True,
    })


def win_lead(client, admin_client, lead_id, client_id=None):
    """Finish the pipeline for a lead (see advance_to_negotiation) and mark it won as the admin - the
    work order and advance, then Won, optionally mapped to an existing client_id (default: a brand-new
    client, named after the lead, since winning no longer guesses by matching names)."""
    advance_to_negotiation(client, lead_id)
    client.patch(f"/api/leads/{lead_id}", json={
        "work_order_no": "WO-1001", "work_order_date": "2026-09-23",
        "advance_amount": 100000, "advance_date": "2026-09-23", "advance_mode": "Bank transfer",
    })
    body = {"stage": "Won"}
    if client_id is not None:
        body["client_id"] = client_id
    res = admin_client.patch(f"/api/leads/{lead_id}", json=body)
    assert res.status_code == 200, res.get_json()
    return res.get_json()

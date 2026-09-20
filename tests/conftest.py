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
        client.get("/")
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

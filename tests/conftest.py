import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.auth import create_user
from app.config import Config
from app.extensions import db
from app.models import Module

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
        db.session.add(Module(key="leads", name="Lead desk", icon="leads", path="/", sort_order=1))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def make_user(name, is_admin=False, pin=PIN):
    """A user who has already set their PIN."""
    user, _ = create_user(name, is_admin=is_admin)
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
def anon(app):
    return app.test_client()

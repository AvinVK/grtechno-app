import pytest

from app import create_app
from app.config import Config
from app.extensions import db


class AuthConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret"
    APP_PASSWORD = "open-sesame"


@pytest.fixture
def client():
    app = create_app(AuthConfig)
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.drop_all()


def csrf(client):
    client.get("/login")
    with client.session_transaction() as s:
        return s["csrf"]


def test_everything_is_locked_until_login(client):
    assert client.get("/").status_code == 302
    assert client.get("/export.csv").status_code == 302
    assert client.get("/api/state").status_code == 401


def test_wrong_and_right_password(client):
    token = csrf(client)
    bad = client.post("/login", data={"csrf": token, "password": "nope"})
    assert bad.status_code == 200 and b"not correct" in bad.data
    ok = client.post("/login", data={"csrf": token, "password": "open-sesame"})
    assert ok.status_code == 302
    assert client.get("/api/state").status_code == 200


def test_login_needs_csrf(client):
    assert client.post("/login", data={"password": "open-sesame"}).status_code == 400


def test_default_secret_refused_when_password_set():
    class Bad(AuthConfig):
        SECRET_KEY = "dev-only-change-me"

    with pytest.raises(RuntimeError):
        create_app(Bad)

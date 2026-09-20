import sqlite3
import subprocess
from pathlib import Path

import pytest
from flask_migrate import upgrade

from app import create_app, deploy
from app.config import Config

SECRET = "s" * 32
HEADERS = {"X-Deploy-Secret": SECRET}
OLD_REVISION = "f6b2d9e13a70"      # before roles, clients and projects were added


class Done:
    def __init__(self, code=0, out="Already up to date.\n", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


@pytest.fixture
def server(tmp_path, monkeypatch):
    """An app on a real SQLite file, a fake WSGI file to touch, and git replaced by a stub."""
    db_file = tmp_path / "leads.db"
    wsgi_file = tmp_path / "wsgi.py"
    wsgi_file.write_text("# reload me")

    class DeployConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(db_file).replace("\\", "/")
        SECRET_KEY = "deploy-test-secret-not-a-placeholder"

    monkeypatch.setenv("DEPLOY_SECRET", SECRET)
    monkeypatch.setenv("WSGI_RELOAD_FILE", str(wsgi_file))
    calls = []
    monkeypatch.setattr(deploy.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), Done())[1])
    app = create_app(DeployConfig)
    app.git_calls, app.wsgi_file, app.db_file = calls, wsgi_file, db_file
    return app


def tables(path):
    c = sqlite3.connect(path)
    try:
        return {r[0] for r in c.execute("select name from sqlite_master where type = 'table'")}
    finally:
        c.close()


# ---------- who may call it ----------

def test_deploy_is_off_without_a_secret(server, monkeypatch):
    monkeypatch.delenv("DEPLOY_SECRET")
    assert server.test_client().post("/deploy", headers=HEADERS).status_code == 403
    monkeypatch.setenv("DEPLOY_SECRET", "too-short")                                 # weak secrets count as off
    assert server.test_client().post("/deploy", headers={"X-Deploy-Secret": "too-short"}).status_code == 403


def test_deploy_needs_the_right_secret_and_post(server):
    client = server.test_client()
    assert client.post("/deploy").status_code == 403
    assert client.post("/deploy", headers={"X-Deploy-Secret": "wrong" * 8}).status_code == 403
    assert client.get("/deploy", headers=HEADERS).status_code in (302, 405)          # only POST is accepted
    assert server.git_calls == []                                                    # nothing ran for any of them


# ---------- what it does ----------

def test_deploy_pulls_migrates_and_reloads(server):
    before = server.wsgi_file.stat().st_mtime_ns
    res = server.test_client().post("/deploy", headers=HEADERS)
    body = res.get_json()
    assert res.status_code == 200 and body["ok"] is True
    assert server.git_calls == [["git", "pull", "--ff-only", "origin", "main"]]
    assert {"users", "leads", "projects", "roles"} <= tables(server.db_file)         # a fresh database is created
    assert server.wsgi_file.stat().st_mtime_ns > before                              # the reload file was touched
    assert body["backup"] is None                                                    # nothing to back up the first time


def test_deploy_backs_up_then_upgrades_an_existing_database(server):
    with server.app_context():
        upgrade(directory=str(deploy.BASE_DIR / "migrations"), revision=OLD_REVISION)
    assert "projects" not in tables(server.db_file)
    c = sqlite3.connect(server.db_file)
    c.execute("insert into users (code, userid, name, is_admin, is_active, failed_attempts, created_at) "
              "values ('1234', 'keep-1234', 'Keep', 0, 1, 0, '2026-01-01')")
    c.commit(); c.close()

    res = server.test_client().post("/deploy", headers=HEADERS)
    body = res.get_json()
    assert res.status_code == 200 and body["backup"]
    assert "projects" in tables(server.db_file)                                      # migrated to the latest
    backup = server.db_file.parent / "backups" / body["backup"]
    assert backup.exists() and "projects" not in tables(backup)                      # the backup is the old version
    kept = sqlite3.connect(server.db_file).execute("select userid from users").fetchall()
    assert kept == [("keep-1234",)]                                                  # existing data survived


def test_only_the_newest_backups_are_kept(server):
    sqlite3.connect(server.db_file).close()
    folder = server.db_file.parent / "backups"
    folder.mkdir()
    for i in range(deploy.KEEP_BACKUPS + 3):
        (folder / f"leads-2020010{i % 10}-0000{i:02d}.db").write_text("old")
    deploy.backup_database(server)
    assert len(list(folder.glob("leads-*.db"))) == deploy.KEEP_BACKUPS


def test_a_failed_pull_stops_everything(server, monkeypatch):
    monkeypatch.setattr(deploy.subprocess, "run", lambda cmd, **kw: Done(1, "", "fatal: cannot fast-forward"))
    before = server.wsgi_file.stat().st_mtime_ns
    res = server.test_client().post("/deploy", headers=HEADERS)
    assert res.status_code == 500 and res.get_json()["step"] == "git pull"
    assert "cannot fast-forward" in res.get_json()["output"]
    assert not server.db_file.exists() and server.wsgi_file.stat().st_mtime_ns == before


def test_a_failed_migration_does_not_reload_the_site(server, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("migration exploded")

    monkeypatch.setattr(deploy, "upgrade", boom)
    before = server.wsgi_file.stat().st_mtime_ns
    res = server.test_client().post("/deploy", headers=HEADERS)
    assert res.status_code == 500 and res.get_json()["step"] == "database"
    assert "migration exploded" in res.get_json()["error"]
    assert server.wsgi_file.stat().st_mtime_ns == before                             # old code keeps running


def test_reload_setup_problems_are_reported(server, monkeypatch):
    monkeypatch.delenv("WSGI_RELOAD_FILE")
    res = server.test_client().post("/deploy", headers=HEADERS)
    assert res.status_code == 500 and res.get_json()["step"] == "reload" and "WSGI_RELOAD_FILE" in res.get_json()["error"]
    monkeypatch.setenv("WSGI_RELOAD_FILE", str(server.wsgi_file.parent / "missing.py"))
    assert server.test_client().post("/deploy", headers=HEADERS).get_json()["step"] == "reload"


def test_it_says_when_requirements_changed(server, monkeypatch):
    hashes = iter(["before", "after"])
    monkeypatch.setattr(deploy, "_requirements_hash", lambda: next(hashes))
    assert server.test_client().post("/deploy", headers=HEADERS).get_json()["requirements_changed"] is True

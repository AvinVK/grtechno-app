"""Deploy webhook, the same idea as Clockit's. PythonAnywhere's free plan cannot drive a console from outside, so
after every push to main a GitHub Action POSTs here (scripts/deploy.py) and this route does the update itself:

    git pull  ->  back up the database  ->  run the migrations  ->  touch the WSGI file (reload)

The migrations run in a fresh Python process (the same command you would type by hand), not inside the web server,
because Alembic reconfigures logging and that clashed with PythonAnywhere's web server ("maximum recursion depth").

It is switched off unless DEPLOY_SECRET (at least 20 characters) is set in the server's .env file, and it only
answers requests that send that secret in the X-Deploy-Secret header."""

import hashlib
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from .config import BASE_DIR

bp = Blueprint("deploy", __name__)

MIN_SECRET_LENGTH = 20
KEEP_BACKUPS = 10
MIGRATION_TIMEOUT = 180


def backup_database(app):
    """Copy the SQLite database to instance/backups/ (a consistent copy, safe while the app is running) and keep the
    newest few. Returns the backup's path, or None when there is no SQLite file yet."""
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///") or uri.endswith(":memory:"):
        return None
    source = Path(uri[len("sqlite:///"):])
    if not source.exists():
        return None
    folder = source.parent / "backups"
    folder.mkdir(exist_ok=True)
    target = folder / f"{source.stem}-{datetime.now():%Y%m%d-%H%M%S}{source.suffix}"
    src, dst = sqlite3.connect(source), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(folder.glob(f"{source.stem}-*{source.suffix}"))[:-KEEP_BACKUPS]:
        old.unlink()
    return target


def _python() -> str:
    """The Python of the site's virtualenv. Inside the web server sys.executable is the server program (uwsgi), not
    Python, so look in the virtualenv instead. PYTHON_BIN in .env overrides all of this."""
    override = (os.environ.get("PYTHON_BIN") or "").strip()
    if override:
        return override
    if Path(sys.executable).name.lower().startswith("python"):
        return sys.executable
    for candidate in (Path(sys.prefix) / "bin" / "python", Path(sys.prefix) / "Scripts" / "python.exe"):
        if candidate.exists():
            return str(candidate)
    return shutil.which("python3") or "python3"


def run_migrations(app):
    """Run `flask db upgrade` against the same database the site uses. Returns (succeeded, output)."""
    env = dict(os.environ, DATABASE_URL=app.config["SQLALCHEMY_DATABASE_URI"])
    result = subprocess.run(
        [_python(), "-m", "flask", "--app", "wsgi", "db", "upgrade"],
        cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=MIGRATION_TIMEOUT,
    )
    return result.returncode == 0, result.stdout + result.stderr


def _requirements_hash() -> str:
    path = BASE_DIR / "requirements.txt"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _fail(step, output, status=500, **extra):
    return jsonify(ok=False, step=step, output=output, **extra), status


@bp.post("/deploy")
def deploy():
    expected = (os.environ.get("DEPLOY_SECRET") or "").strip()
    provided = request.headers.get("X-Deploy-Secret", "").strip()
    if len(expected) < MIN_SECRET_LENGTH or not secrets.compare_digest(provided, expected):
        return jsonify(error="forbidden"), 403

    before = _requirements_hash()
    pull = subprocess.run(
        ["git", "pull", "--ff-only", "origin", "main"],
        cwd=BASE_DIR, capture_output=True, text=True, timeout=60,
    )
    output = pull.stdout + pull.stderr
    if pull.returncode != 0:
        return _fail("git pull", output)

    try:
        backup = backup_database(current_app)
    except Exception as err:
        return _fail("database backup", output, error=repr(err))
    try:
        migrated, migration_output = run_migrations(current_app)
    except Exception as err:                                   # for example the migration ran out of time
        migrated, migration_output = False, repr(err)
    if not migrated:                                           # the site keeps running the old code until reload
        return _fail("database", f"{output}\n{migration_output}",
                     error="the database migration failed, so the site was not reloaded",
                     backup=backup.name if backup else None)

    reload_file = (os.environ.get("WSGI_RELOAD_FILE") or "").strip()
    if not reload_file:
        return _fail("reload", output, error="WSGI_RELOAD_FILE is not set in .env")
    try:
        os.utime(reload_file, None)
    except OSError as err:
        return _fail("reload", output, error=str(err))

    return jsonify(
        ok=True, output=output, backup=backup.name if backup else None,
        requirements_changed=_requirements_hash() != before,
    )

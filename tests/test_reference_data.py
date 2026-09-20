"""The migration keeps its own copy of the starting data. This test builds a database through the real
migrations and checks the copy has not drifted from app/reference_data.py."""

import os
import subprocess
import sys
import tempfile

import sqlite3

from app import reference_data as ref

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_migrations_seed_the_same_data_as_reference_data():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "check.db")
        env = dict(os.environ, DATABASE_URL="sqlite:///" + path.replace("\\", "/"))
        run = subprocess.run([sys.executable, "-m", "flask", "--app", "wsgi", "db", "upgrade"],
                             cwd=APP, env=env, capture_output=True, text=True)
        assert run.returncode == 0, run.stderr[-500:]

        c = sqlite3.connect(path)
        assert c.execute("select key, name, sees_all from roles order by rowid").fetchall() == [
            (k, n, int(s)) for k, n, s in ref.ROLES]
        rows = c.execute("select role_key, module_key from role_modules").fetchall()
        assert sorted(rows) == sorted((r, m) for r, keys in ref.ROLE_MODULES.items() for m in keys)
        assert c.execute("select key, name, icon, path, sort_order from modules where key != 'leads' order by sort_order").fetchall() == [
            tuple(m) for m in ref.NEW_MODULES]
        assert [r[0] for r in c.execute("select name from site_categories order by sort_order")] == ref.SITE_CATEGORIES
        assert [r[0] for r in c.execute("select name from services where is_active = 1 order by sort_order")] == ref.SERVICES
        hidden = {r[0] for r in c.execute("select name from services where is_active = 0")}
        assert hidden == set(ref.OLD_SERVICES)
        c.close()

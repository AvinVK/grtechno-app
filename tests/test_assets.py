import re

from flask import render_template_string

from app import create_app
from app.config import Config


def test_pages_link_files_with_a_fingerprint(client):
    html = client.get("/").get_data(as_text=True)
    for name in ("css/app.css", "js/common.js", "js/shell.js", "js/app.js"):
        assert re.search(rf'/static/{re.escape(name)}\?v=[0-9a-f]{{10}}"', html), name
    login = create_app(type("T", (Config,), {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                                             "SECRET_KEY": "asset-test-secret-not-a-placeholder"})).test_client()
    assert re.search(r"/static/css/app\.css\?v=[0-9a-f]{10}", login.get("/login").get_data(as_text=True))


def test_the_address_changes_when_the_file_changes_and_not_otherwise(app, tmp_path):
    (tmp_path / "x.js").write_text("one")
    app.static_folder = str(tmp_path)
    with app.test_request_context():
        first = render_template_string("{{ asset('x.js') }}")
        assert render_template_string("{{ asset('x.js') }}") == first            # same file, same address
        (tmp_path / "x.js").write_text("two!")
        second = render_template_string("{{ asset('x.js') }}")
        assert second != first and second.startswith("/static/x.js?v=")          # a deploy changed it
        assert render_template_string("{{ asset('missing.js') }}") == "/static/missing.js"   # no crash on a missing file


def test_pages_are_never_reused_from_the_browser_cache(client, anon):
    assert client.get("/").headers["Cache-Control"] == "no-cache"
    assert anon.get("/login").headers["Cache-Control"] == "no-cache"

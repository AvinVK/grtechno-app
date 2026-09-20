"""Cache busting. Browsers keep CSS and JavaScript files and do not notice when a deploy changes them, so people
would see the old app until they hard-refreshed. asset("js/app.js") returns /static/js/app.js?v=<fingerprint of
the file's content>: when a deploy changes the file, the address changes and every browser fetches the new one.
Pages themselves are marked no-cache, so the new addresses are picked up on the next normal load."""

import hashlib
from pathlib import Path

from flask import url_for


def register_assets(app):
    seen = {}                                        # filename -> ((mtime, size), fingerprint)

    def asset(filename: str) -> str:
        path = Path(app.static_folder) / filename
        try:
            stat = path.stat()
        except OSError:
            return url_for("static", filename=filename)
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = seen.get(filename)
        if cached is None or cached[0] != stamp:
            cached = (stamp, hashlib.sha1(path.read_bytes()).hexdigest()[:10])
            seen[filename] = cached
        return url_for("static", filename=filename, v=cached[1])

    app.jinja_env.globals["asset"] = asset

    @app.after_request
    def pages_are_never_reused(response):
        if response.mimetype == "text/html":
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

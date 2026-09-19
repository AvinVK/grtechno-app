import hmac
import secrets

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

bp = Blueprint("auth", __name__)


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf() -> None:
    expected = session.get("csrf")
    sent = request.form.get("csrf", "")
    # An empty session token must never match an empty form value.
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "Your session expired. Reload the page and try again.")


@bp.before_app_request
def require_login():
    if not current_app.config["APP_PASSWORD"]:
        return None
    if request.endpoint in ("auth.login", "static") or session.get("auth"):
        return None
    if request.path.startswith("/api/"):
        return jsonify(error="Not signed in"), 401
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not current_app.config["APP_PASSWORD"]:
        return redirect(url_for("views.index"))
    error = None
    if request.method == "POST":
        check_csrf()
        supplied = request.form.get("password", "")
        expected = current_app.config["APP_PASSWORD"]
        if hmac.compare_digest(supplied.encode(), expected.encode()):
            session.clear()
            session["auth"] = True
            session.permanent = True
            return redirect(url_for("views.index"))
        error = "That password is not correct."
    return render_template("login.html", error=error)


@bp.post("/logout")
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("auth.login"))

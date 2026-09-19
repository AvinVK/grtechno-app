import hmac
import re
import secrets
from datetime import timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .models import Lead, User, utcnow

bp = Blueprint("auth", __name__)

SETUP_CODE_DAYS = 7
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=5)
MIN_PASSWORD = 8
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I so a code read aloud is not misheard
PUBLIC_ENDPOINTS = {"auth.login", "auth.set_password", "static"}
LOCKED_MESSAGE = "Too many wrong tries. Wait 5 minutes and try again."
_DUMMY_HASH = generate_password_hash("not-a-real-password")


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


# ---------- users and codes ----------

def _normalize_code(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text or "").upper()


def issue_setup_code(user: User) -> str:
    """Give the user a fresh one-time setup code and switch off their current password."""
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    user.setup_code_hash = generate_password_hash(raw)
    user.setup_code_expires = utcnow() + timedelta(days=SETUP_CODE_DAYS)
    user.password_hash = None
    user.failed_attempts = 0
    user.locked_until = None
    return f"{raw[:4]}-{raw[4:]}"


def create_user(name: str, is_admin: bool = False, code: str = None):
    """Add a user (not yet committed). Returns (user, setup_code). Raises ValueError on a bad name or code.
    The 4-digit code is chosen at random unless one is given."""
    name = " ".join((name or "").split())[:60]
    slug = re.sub(r"[^a-z0-9]", "", name.lower())[:20]
    if not slug:
        raise ValueError("Use letters or numbers in the name.")
    if code is not None:
        if not re.fullmatch(r"[1-9][0-9]{3}", code):
            raise ValueError("The code must be 4 digits, from 1000 to 9999.")
        if db.session.get(User, code) is not None:
            raise ValueError(f"The code {code} is already used by another user.")
    else:
        for _ in range(200):
            code = str(1000 + secrets.randbelow(9000))
            if db.session.get(User, code) is None:
                break
        else:
            raise ValueError("No free user codes are left.")
    user = User(code=code, userid=f"{slug}-{code}", name=name, is_admin=is_admin)
    setup_code = issue_setup_code(user)
    db.session.add(user)
    return user, setup_code


def find_user(userid_text: str):
    text = (userid_text or "").strip().lower()
    if "-" not in text:
        return None
    user = db.session.get(User, text.rsplit("-", 1)[1])
    return user if user and user.userid == text else None


def visible_leads():
    """Leads the signed-in person may see: everything for the admin, otherwise only their own."""
    query = Lead.query
    if not g.user.is_admin:
        query = query.filter(Lead.owner_code == g.user.code)
    return query


def _is_locked(user) -> bool:
    return bool(user and user.locked_until and user.locked_until > utcnow())


def _register_failure(user) -> None:
    if user is None:
        return
    user.failed_attempts += 1
    if user.failed_attempts >= MAX_FAILURES:
        user.failed_attempts = 0
        user.locked_until = utcnow() + LOCKOUT
    db.session.commit()


def _setup_code_ok(user, code: str) -> bool:
    return bool(
        user
        and user.is_active
        and user.setup_code_hash
        and user.setup_code_expires
        and user.setup_code_expires > utcnow()
        and check_password_hash(user.setup_code_hash, code)
    )


# ---------- request hooks ----------

@bp.before_app_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        user = db.session.get(User, uid)
        # A reset clears the password, which also ends any session that was still open.
        if user and user.is_active and user.password_hash:
            g.user = user
        else:
            session.pop("uid", None)
    if g.user or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if request.path.startswith("/api/"):
        return jsonify(error="Not signed in"), 401
    return redirect(url_for("auth.login"))


# ---------- pages ----------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("views.index"))
    error = None
    if request.method == "POST":
        check_csrf()
        user = find_user(request.form.get("userid", ""))
        password = request.form.get("password", "")
        if _is_locked(user):
            error = LOCKED_MESSAGE
        else:
            has_password = bool(user and user.password_hash)
            # Always run one hash check so a wrong userid takes as long as a wrong password.
            matches = check_password_hash(user.password_hash if has_password else _DUMMY_HASH, password)
            if matches and has_password and not user.is_active:
                error = "This account is switched off. Ask your admin."
            elif matches and has_password:
                user.failed_attempts = 0
                db.session.commit()
                session.clear()
                session["uid"] = user.code
                session.permanent = True
                return redirect(url_for("views.index"))
            else:
                _register_failure(user)
                error = "Wrong userid or password."
    return render_template("login.html", error=error, userid=request.form.get("userid", ""))


@bp.route("/set-password", methods=["GET", "POST"])
def set_password():
    if g.user:
        return redirect(url_for("views.index"))
    error = None
    userid = request.form.get("userid", "") if request.method == "POST" else request.args.get("userid", "")
    if request.method == "POST":
        check_csrf()
        user = find_user(userid)
        code = _normalize_code(request.form.get("code", ""))
        password = request.form.get("password", "")
        if _is_locked(user):
            error = LOCKED_MESSAGE
        elif not _setup_code_ok(user, code):
            _register_failure(user)
            error = "That userid and setup code do not match, or the code has expired. Ask your admin for a new code."
        elif len(password) < MIN_PASSWORD:
            error = f"Use at least {MIN_PASSWORD} characters."
        elif password != request.form.get("confirm", ""):
            error = "The two passwords are different."
        elif password.lower() in (user.userid, user.name.lower()):
            error = "Choose a password that is not your name or userid."
        else:
            user.password_hash = generate_password_hash(password)
            user.setup_code_hash = None
            user.setup_code_expires = None
            user.failed_attempts = 0
            user.locked_until = None
            db.session.commit()
            flash("Password saved. Sign in with your userid and new password.", "ok")
            return redirect(url_for("auth.login"))
    return render_template("set_password.html", error=error, userid=userid, min_length=MIN_PASSWORD)


@bp.post("/logout")
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("auth.login"))

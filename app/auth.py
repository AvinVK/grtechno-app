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
from sqlalchemy import false as sa_false, or_
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .models import Attendance, Client, Lead, Project, Role, User, Worker, utcnow

bp = Blueprint("auth", __name__)

SETUP_CODE_DAYS = 7
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=5)
PIN_LENGTH = 6
CODE_ALPHABET = "23456789"   # digits only (no 0/1, read aloud or misread for O/I) - one keyboard to type
                              # on a phone, instead of switching between letters and numbers typing it in
PUBLIC_ENDPOINTS = {"auth.login", "auth.set_pin", "deploy.deploy", "static"}
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


def pin_problem(pin: str, confirm: str):
    """Why this PIN cannot be used, or None if it is fine. A 6-digit PIN has few possibilities, so the
    obvious ones are refused; the account lockout below is what stops guessing."""
    if not re.fullmatch(r"[0-9]{%d}" % PIN_LENGTH, pin):
        return f"Use exactly {PIN_LENGTH} digits."
    if pin != confirm:
        return "The two PINs are different."
    steps = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    if len(set(pin)) == 1 or steps in ({1}, {-1}):
        return "Choose a PIN that is not one repeated digit or a simple run like 123456."
    return None


def _name_prefix(name: str) -> str:
    """The setup code's first 4 characters - built from the person's own name, so the code visibly belongs
    to them instead of reading as a random string they have to double-check against a list (kohal, 2026-10-
    15). Padded with random characters from CODE_ALPHABET if the name has fewer than 4 letters/digits to
    give - still unambiguous, just not fully name-derived for a very short name."""
    letters = re.sub(r"[^A-Za-z0-9]", "", name or "").upper()[:4]
    while len(letters) < 4:
        letters += secrets.choice(CODE_ALPHABET)
    return letters


def issue_setup_code(user: User) -> str:
    """Give the user a fresh one-time setup code and switch off their current PIN. The first 4 characters
    are their own name (see _name_prefix); the last 4 are the actual random secret."""
    raw = _name_prefix(user.name) + "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
    user.setup_code_hash = generate_password_hash(raw)
    user.setup_code_expires = utcnow() + timedelta(days=SETUP_CODE_DAYS)
    user.password_hash = None
    user.failed_attempts = 0
    user.locked_until = None
    return f"{raw[:4]}-{raw[4:]}"


def create_user(name: str, is_admin: bool = False, code: str = None, role: str = None):
    """Add a user (not yet committed). Returns (user, setup_code). Raises ValueError on a bad name, code or role.
    The 4-digit code is chosen at random unless one is given. The role defaults to admin / field sales."""
    role = role or ("admin" if is_admin else "sales_field")
    if db.session.get(Role, role) is None:
        raise ValueError("Choose a role from the list.")
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
    user = User(code=code, userid=f"{slug}-{code}", name=name, is_admin=is_admin, role_key=role)
    setup_code = issue_setup_code(user)
    db.session.add(user)
    return user, setup_code


def sync_worker_for_user(user: User) -> None:
    """Make sure a non-admin User also has a matching Worker (Employee management) row, linked by
    user_code - so they show up wherever Workers do (Enquired by, surveyor...) without being added twice.
    Only once they've actually signed in for the first time (set_pin, below) - a user who was only ever
    added and never activated (declined the job, a typo'd duplicate...) shouldn't clutter Employee
    management with a row that never becomes a real person. Also called whenever their role changes, so
    the two stay in step from then on; never deletes or turns one off from here - a user's own attendance/
    HR history on the Worker side shouldn't disappear just because their login does.

    Before creating a new row, checks for an already-existing Worker with the same name that has no User
    of its own yet (typically someone already tracked from the WhatsApp attendance import, now also given
    a login) and links to that one instead - otherwise the same real person ends up listed twice. Only
    when the name matches exactly one such Worker; an ambiguous or absent match still gets a new row."""
    if user.is_admin or not user.password_hash:
        return
    worker = Worker.query.filter_by(user_code=user.code).first()
    if worker is None:
        candidates = Worker.query.filter(
            Worker.user_code.is_(None), db.func.lower(Worker.name) == user.name.strip().lower(),
        ).all()
        worker = candidates[0] if len(candidates) == 1 else None
        if worker is None:
            worker = Worker(category="staff", source="user_account")
            db.session.add(worker)
        worker.user_code = user.code
    worker.name = user.name
    worker.role_key = user.role_key


def find_user(userid_text: str):
    # Forgiving the same way the setup code is: a phone keyboard can slip in a stray space around the
    # dash, or autocorrect it to an en/em dash, without the person noticing - none of that should turn
    # into "wrong userid or code".
    text = re.sub(r"\s+", "", userid_text or "").lower().replace("–", "-").replace("—", "-")
    if "-" not in text:
        return None
    user = db.session.get(User, text.rsplit("-", 1)[1])
    return user if user and user.userid == text else None


def visible_leads():
    """Leads the signed-in person may see: everything for the admin, any sees_all role (full admin-like
    access - Company Director, Office Assistant cum client consultant) and Sales (office) specifically -
    every lead, but deliberately not sees_all's wider powers (everyone's attendance and the right to
    delete it, project-manager assignment) which they were never asked to have (kohal's access matrix,
    2026-10-14). Otherwise only their own."""
    query = Lead.query
    if not (g.user.is_admin or g.user.sees_all or g.user.role_key == "sales_office"):
        query = query.filter(Lead.owner_code == g.user.code)
    return query


#  Site supervisor and Alarm Tech cum site supervisor were set up as the same access from the start
# (kohal's access matrix, 2026-10-14: "Site supervisor = same as Alarm Tech cum site sup") - both get a
# project only once they've actually checked into it (kohal, 2026-10-16), not by ownership/management.
SITE_SUPERVISOR_ROLE_KEYS = {"supervisor", "alarm_tech_cum_site_supervisor"}


def visible_projects():
    """Projects this person may see: everything for the admin, for roles marked sees_all (Accounts), and
    for Project manager specifically (kohal, 2026-10-16 - deliberately not sees_all itself, to avoid also
    granting its other powers: everyone's attendance, deleting a record, assigning project managers). Only
    their assigned state(s) for a sub-admin. A site supervisor only sees a project once they've checked
    into it via Attendance - not by ownership/management, unlike everyone else's fallback below."""
    query = Project.query
    if g.user.sees_all or g.user.role_key == "project_manager":
        return query
    if g.user.role_key == "sub_admin":
        states = g.user.state_names
        return query.filter(Project.site_state.in_(states)) if states else query.filter(sa_false())
    if g.user.role_key in SITE_SUPERVISOR_ROLE_KEYS:
        checked_in = (db.session.query(Attendance.project_id)
                      .filter(Attendance.user_code == g.user.code, Attendance.project_id.isnot(None)))
        return query.filter(Project.id.in_(checked_in))
    return query.filter(or_(Project.owner_code == g.user.code, Project.manager_code == g.user.code))


# Who may approve a material movement (kohal, 2026-10-16) - see MaterialMovement.status. Checked fresh at
# approval time, not fixed when the request was made, so it doesn't matter who's on site or assigned as
# manager *now* versus when the request went in.

def can_approve_issue(user, project) -> bool:
    """An issue ('out') to a project: the admin, any project manager - every one of them, not just whoever
    happens to be that specific project's assigned manager_code (kohal, 2026-10-16: "project manager should
    have access to approve any request, he is the pm for all of the projects" - the same role that already
    sees every project, see visible_projects) - or a site supervisor currently checked into that exact
    project right now (an open Attendance session with project_id set to it); being a site supervisor
    elsewhere, or having checked into it earlier today and since checked out, isn't enough."""
    if user.is_admin:
        return True
    if project is None:
        return False
    if user.role_key == "project_manager":
        return True
    if user.role_key in SITE_SUPERVISOR_ROLE_KEYS:
        return Attendance.query.filter_by(user_code=user.code, project_id=project.id, check_out_at=None).first() is not None
    return False


def can_approve_stock_in(user) -> bool:
    """A stock-in ('in'): the admin, or an accountant / office assistant - "office incharge" in kohal's own
    words, 2026-10-16."""
    return user.is_admin or user.role_key in ("accounts", "office_assistant")


def visible_clients():
    """Clients this person may see: everything for sees_all, only their assigned state(s) for a sub-admin,
    otherwise the ones they created plus the clients of projects they manage."""
    query = Client.query
    if g.user.sees_all:
        return query
    if g.user.role_key == "sub_admin":
        states = g.user.state_names
        return query.filter(Client.state.in_(states)) if states else query.filter(sa_false())
    managed = db.session.query(Project.client_id).filter(Project.manager_code == g.user.code)
    return query.filter(or_(Client.owner_code == g.user.code, Client.id.in_(managed)))


def visible_attendance():
    """Attendance rows this person may see: everyone's for sees_all (Admin, Accounts), otherwise only their own."""
    query = Attendance.query
    if not g.user.sees_all:
        query = query.filter(Attendance.user_code == g.user.code)
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
        # A reset clears the PIN, which also ends any session that was still open.
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
        pin = request.form.get("pin", "")
        if _is_locked(user):
            error = LOCKED_MESSAGE
        else:
            has_pin = bool(user and user.password_hash)
            # Always run one hash check so a wrong userid takes as long as a wrong PIN.
            matches = check_password_hash(user.password_hash if has_pin else _DUMMY_HASH, pin)
            if matches and has_pin and not user.is_active:
                error = "This account is switched off. Ask your admin."
            elif matches and has_pin:
                user.failed_attempts = 0
                db.session.commit()
                session.clear()
                session["uid"] = user.code
                session.permanent = True
                return redirect(url_for("views.index"))
            else:
                _register_failure(user)
                error = "Wrong userid or PIN."
    return render_template("login.html", error=error, userid=request.form.get("userid", ""))


@bp.route("/set-pin", methods=["GET", "POST"])
def set_pin():
    if g.user:
        return redirect(url_for("views.index"))
    error = None
    userid = request.form.get("userid", "") if request.method == "POST" else request.args.get("userid", "")
    if request.method == "POST":
        check_csrf()
        user = find_user(userid)
        code = _normalize_code(request.form.get("code", ""))
        pin = request.form.get("pin", "")
        if _is_locked(user):
            error = LOCKED_MESSAGE
        elif not _setup_code_ok(user, code):
            _register_failure(user)
            error = "That userid and setup code do not match, or the code has expired. Ask your admin for a new code."
        else:
            error = pin_problem(pin, request.form.get("confirm", ""))
            if error is None:
                user.password_hash = generate_password_hash(pin)      # stored as a hash, never the PIN itself
                user.setup_code_hash = None
                user.setup_code_expires = None
                user.failed_attempts = 0
                user.locked_until = None
                sync_worker_for_user(user)       # first time active (or reactivated after a reset) - see there
                db.session.commit()
                flash("PIN saved. Sign in with your userid and new PIN.", "ok")
                return redirect(url_for("auth.login"))
    return render_template("set_pin.html", error=error, userid=userid, pin_length=PIN_LENGTH)


@bp.post("/logout")
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("auth.login"))

import hmac
import re
import secrets
from datetime import time, timedelta

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

from .constants import CHANDRAPUR_DISTRICT, COMMISSION_ROLE_KEY
from .extensions import db
from .models import Attendance, Client, Lead, Project, Role, User, Worker, utcnow
from .modules import has_module
from .timeutil import to_local

bp = Blueprint("auth", __name__)

SETUP_CODE_DAYS = 7
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=5)
PIN_LENGTH = 6
CODE_ALPHABET = "23456789"   # digits only (no 0/1, read aloud or misread for O/I) - one keyboard to type
                              # on a phone, instead of switching between letters and numbers typing it in
PUBLIC_ENDPOINTS = {"auth.login", "auth.set_pin", "deploy.deploy", "static"}


def _landing_url(user) -> str:
    """Where someone lands right after signing in (kohal, 2026-10-21: "make admin landing page as me tab
    and other landing pages as attendnace tab") - the admin's own Me hub, everyone else's Attendance. The
    Leads tab itself still goes through views.index as always (it's still "/", same URL the bottom nav's
    own Leads tab links to) - this only decides where login/set-pin send someone, not what "/" renders for
    a leads-having role navigating there on their own afterwards.

    A client (kohal, 2026-10-22) has no Attendance to check into at all - their own portal instead."""
    if user.is_admin:
        return url_for("me.page")
    if user.role_key == "client":
        return url_for("client_portal.welcome")
    return url_for("attendance.page")


def _safe_next(value):
    """A login redirect target is attacker-controllable input (it rides along in the URL) - only ever a
    same-origin relative path, never an absolute URL or a protocol-relative //host one, so it can't be used
    to bounce someone off-site."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    return value
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


def create_user(name: str, is_admin: bool = False, code: str = None, role: str = None, userid: str = None):
    """Add a user (not yet committed). Returns (user, setup_code). Raises ValueError on a bad name, code,
    role or userid. The 4-digit code is chosen at random unless one is given. The role defaults to admin /
    field sales. userid defaults to name-code; pass one explicitly to use something else instead (kohal,
    2026-10-23: "the login of client should be mapped to its mobile number... so number will be the mapping
    key" - see app/clients.py's give_login, which passes the client's own phone number here)."""
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
    if userid is not None:
        userid = userid.strip().lower()
        if not userid:
            raise ValueError("Enter a valid userid.")
        if User.query.filter_by(userid=userid).first() is not None:
            raise ValueError(f"{userid} is already used by another login.")
    else:
        userid = f"{slug}-{code}"
    user = User(code=code, userid=userid, name=name, is_admin=is_admin, role_key=role)
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
    when the name matches exactly one such Worker; an ambiguous or absent match still gets a new row.

    A client login never gets one at all (kohal, 2026-10-22) - a customer isn't an employee, and Worker
    is Employee management's own table; one here would just be a fake "staff" row for every client."""
    if user.is_admin or user.role_key == "client" or not user.password_hash:
        return
    worker = Worker.query.filter_by(user_code=user.code).first()
    if worker is None:
        candidates = Worker.query.filter(
            Worker.user_code.is_(None), db.func.lower(Worker.name) == user.name.strip().lower(),
        ).all()
        worker = candidates[0] if len(candidates) == 1 else None
        if worker is None:
            worker = Worker(category="staff", source="user_account")
            if user.role_key in SITE_TRADE_ROLE_KEYS:
                worker.employment_type = "daily_wages"
                worker.fooding_opt_in = True
            db.session.add(worker)
        worker.user_code = user.code
    worker.name = user.name
    worker.role_key = user.role_key


def find_user(userid_text: str):
    # Forgiving the same way the setup code is: a phone keyboard can slip in a stray space around the
    # dash, or autocorrect it to an en/em dash, without the person noticing - none of that should turn
    # into "wrong userid or code". A plain lookup on the (unique) userid column, not the old "assume
    # name-code and reverse-engineer the code" trick - that broke for a client's own phone-number userid,
    # which has no dash at all (kohal, 2026-10-23).
    text = re.sub(r"\s+", "", userid_text or "").lower().replace("–", "-").replace("—", "-")
    if not text:
        return None
    return User.query.filter_by(userid=text).first()


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
# Contractor FAPA (kohal, 2026-10-19: "he needs to be given site supervisor access") joins them the same
# way Project manager Chandrapur joined PROJECT_MANAGER_ROLE_KEYS below - a custom role, module access set
# up directly in the database (see app/roles.py), this set is what actually gives it the role's powers.
SITE_SUPERVISOR_ROLE_KEYS = {"supervisor", "alarm_tech_cum_site_supervisor", "contractor_fapa"}

# Project manager Chandrapur (kohal, 2026-10-18: "alocate chandrapur region projects and all other access
# as project manager to project manager chandrapur role") - counts as a project manager everywhere else
# (approving attendance, auto-assigned as a project's manager when it creates one, appearing in the
# manager-assignment picker - see app/projects.py), but its own project *visibility* is scoped to the
# Chandrapur district specifically rather than every project company-wide (see visible_projects below) -
# that was the one thing asked for by name, not folded into "sees everything" like the plain role is.
PROJECT_MANAGER_ROLE_KEYS = {"project_manager", COMMISSION_ROLE_KEY}

# "Site trades: they sign in only to check themselves in and out" (reference_data.py) - day labour, so a
# brand-new Worker row for one of them starts on the fooding wallet and the Wages tile by default, same as
# Employee management's own "automatically on for daily wages" default (kohal, 2026-10-23: "why cant he see
# fooding and workplan and his attendance history... whatever things he shuld be able to see as daily
# wages") - see sync_worker_for_user below. Workplan itself needs no change here: a worker's own assignment
# alert (app/me.py's my_work_assignment) is already shown regardless of module access, by design.
SITE_TRADE_ROLE_KEYS = {"welder", "fitter", "helper", "alarm_technician"}


def visible_projects(user=None):
    """Projects this person may see: everything for the admin, for roles marked sees_all (Accounts), and
    for Project manager specifically (kohal, 2026-10-16 - deliberately not sees_all itself, to avoid also
    granting its other powers: everyone's attendance, deleting a record, assigning project managers). Only
    their assigned state(s) for a sub-admin. Project manager Chandrapur sees every project in that district,
    plus (same as everyone's own fallback below) anything it personally owns or manages elsewhere. A site
    supervisor only sees a project once they've checked into it via Attendance - not by ownership/
    management, unlike everyone else's fallback below.

    Defaults to the signed-in user (every caller in a request); can_approve_attendance passes its own
    `user` explicitly instead, since it's also called directly in tests with no request/g.user around."""
    user = user or g.user
    query = Project.query
    if user.sees_all or user.role_key == "project_manager":
        return query
    if user.role_key == COMMISSION_ROLE_KEY:
        return query.filter(or_(Project.site_district == CHANDRAPUR_DISTRICT,
                                 Project.owner_code == user.code, Project.manager_code == user.code))
    if user.role_key == "sub_admin":
        states = user.state_names
        return query.filter(Project.site_state.in_(states)) if states else query.filter(sa_false())
    if user.role_key == "client":
        # Exactly the one customer this login was set up as (kohal, 2026-10-22: "client should only be
        # able to see the projects they belong to") - never by ownership/management like the fallback
        # below, a client never owns or manages anything here.
        return query.filter(Project.client_id == user.client_id) if user.client_id else query.filter(sa_false())
    if user.role_key in SITE_SUPERVISOR_ROLE_KEYS:
        checked_in = (db.session.query(Attendance.project_id)
                      .filter(Attendance.user_code == user.code, Attendance.project_id.isnot(None)))
        return query.filter(Project.id.in_(checked_in))
    return query.filter(or_(Project.owner_code == user.code, Project.manager_code == user.code))


# Who may approve a material movement (kohal, 2026-10-16) - see MaterialMovement.status. Checked fresh at
# approval time, not fixed when the request was made.

def can_approve_issue(user) -> bool:
    """An issue ('out'): the admin, or anyone with Inventory access (kohal, 2026-10-17 - moved off the
    project's own manager/checked-in supervisor, since approving now also records who physically took the
    material out of the store and how it got there, which is an Inventory-side action, done from Inventory's
    own Material requests tab, not the project's). check_module("inventory") already gates every Inventory
    route the same way, so this only matters for deciding what to show outside that module (e.g. the Me
    hub)."""
    return user.is_admin or has_module(user, "inventory")


def can_approve_stock_in(user) -> bool:
    """A stock-in ('in'): the admin, or an accountant / office assistant - "office incharge" in kohal's own
    words, 2026-10-16."""
    return user.is_admin or user.role_key in ("accounts", "office_assistant")


def can_manage_fooding(user) -> bool:
    """Who may allot a daily-wage worker's food money, or pause/resume their own ₹200/day deduction (kohal,
    2026-10-18: "the admin or accountant will alot some money... unless admin or accountant pauses that
    feature") - narrower than can_approve_stock_in's "office incharge" too, since this one was only ever
    named as the admin or accountant specifically."""
    return user.is_admin or user.role_key == "accounts"


def can_manage_cash_purchases(user) -> bool:
    """Who may hand an employee cash to buy something with, and who may approve or reject what they say
    they bought with it (kohal, 2026-10-21: "cash given by admin -> purchase recorded by employee and
    approved by admin") - same admin-or-accountant pair as fooding, both sides of the same money-handling
    job."""
    return user.is_admin or user.role_key == "accounts"


def can_draft_work_plan(user) -> bool:
    """Who may draft tomorrow's work assignments (kohal, 2026-10-19: "Next day work scheduling by project
    manager or by accountant or admin") - a project manager (any of PROJECT_MANAGER_ROLE_KEYS), the
    accountant, or the admin. check_module("workplan") already gates the page the same way; this is for
    deciding what to show outside it (the Me hub)."""
    return user.is_admin or user.role_key in PROJECT_MANAGER_ROLE_KEYS or user.role_key == "accounts"


def can_approve_work_assignment(user) -> bool:
    """Who may approve one (kohal, 2026-10-19: "This allotment should approved by Admin") - the admin,
    literally, not Company Director or anyone else who stands in for "admin" elsewhere in this app."""
    return user.is_admin


def can_send_announcement(user) -> bool:
    """Who may send one (kohal, 2026-10-19: admin only, no approval step - unlike a work assignment, an
    announcement is purely informational)."""
    return user.is_admin


# A daily-wage worker's shift rules (kohal, 2026-10-19: "checkedin after this [7-7.30] then only Admin can
# approve", "checkout after 7.00 pm", "Multiple check in and check out approved by project manager only") -
# nobody else's attendance is held to these; a salaried/contractor check-in or office/marketing work follows
# the normal rule further down no matter what time it happens.
LATE_CHECKIN_CUTOFF = time(7, 30)
EARLY_CHECKOUT_CUTOFF = time(19, 0)


def _is_daily_wage(user) -> bool:
    worker = Worker.query.filter_by(user_code=user.code).first()
    return worker is not None and worker.employment_type == "daily_wages"


def attendance_restriction(user, project, check_in_at, *, exclude_id=None):
    """None, or why this session needs a stricter approver than can_approve_attendance's normal rule - only
    for a daily-wage worker's own session:
    - 'late': checked in after 7:30am - only the admin can approve it, not Company Director, a project
      manager, or a site supervisor either.
    - 'multi_project': a second (or later) session that day against a different project than an earlier one
      that same day - the admin, Company Director, or a project manager who can see that project, but not a
      site supervisor (kohal: "multiple check in and check out approved by project manager only").
    An early checkout (after EARLY_CHECKOUT_CUTOFF) deliberately isn't one of these - kohal, 2026-10-19,
    chose to leave that one on the normal approver list rather than narrow it too.

    Recomputed from the row's own data every time (check_in_at, project, and that day's other sessions),
    never stored, so it can't drift from what actually happened later. exclude_id leaves the row itself out
    of "that day's other sessions" when re-checking an existing record, which would otherwise always find
    itself."""
    if not _is_daily_wage(user):
        return None
    if to_local(check_in_at).time() > LATE_CHECKIN_CUTOFF:
        return "late"
    same_day = Attendance.query.filter_by(user_code=user.code, work_date=to_local(check_in_at).date())
    if exclude_id is not None:
        same_day = same_day.filter(Attendance.id != exclude_id)
    project_id = project.id if project else None
    if any(a.project_id != project_id for a in same_day.all()):
        return "multi_project"
    return None


def can_approve_attendance(user, project, restriction=None) -> bool:
    """A check-in/check-out record (kohal, 2026-10-16: "Attendance should be approved by project manager or
    site supervisor who is checked in on tha project"): the admin or Company Director always - the universal
    fallback, since office/marketing work has no project to approve against, and a site supervisor can't
    approve their own attendance just by being the one checked in - any project manager (on a project they
    can actually see - visible_projects() already narrows this to the Chandrapur district, plus anything
    personally owned/managed, for Project manager Chandrapur specifically; kohal, 2026-10-19: "pm chandrapur
    should only be getting ... attendance approvals only for the projects which he has access to"), or a
    site supervisor currently checked into that exact project right now.

    `restriction` (see attendance_restriction) narrows that for a daily-wage worker's exception cases: 'late'
    means only the admin, 'multi_project' means the admin, Company Director, or an actual project manager -
    never a site supervisor either way. Leave it out (the default) for the normal rule above."""
    if restriction == "late":
        return user.is_admin
    if restriction == "multi_project":
        if user.is_admin or user.role_key == "company_director":
            return True
        if project is None:
            return False
        return user.role_key in PROJECT_MANAGER_ROLE_KEYS and visible_projects(user).filter(Project.id == project.id).first() is not None
    if user.is_admin or user.role_key == "company_director":
        return True
    if project is None:
        return False
    if user.role_key in PROJECT_MANAGER_ROLE_KEYS:
        return visible_projects(user).filter(Project.id == project.id).first() is not None
    if user.role_key in SITE_SUPERVISOR_ROLE_KEYS:
        return Attendance.query.filter_by(user_code=user.code, project_id=project.id, check_out_at=None).first() is not None
    return False


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


# ---------- a client signs in with their phone number alone ----------
# (kohal, 2026-10-26: "no need for setup code as well... that client just needs to enter the contact and see
# the projects") - so the phone number is the only secret there is. Wrong numbers are therefore throttled per
# address: past CLIENT_MISS_LIMIT misses inside CLIENT_MISS_WINDOW, that address waits, which makes walking
# through phone numbers one by one impractical. Kept in memory per process - a soft brake, not a ledger.

CLIENT_MISS_LIMIT = 8
CLIENT_MISS_WINDOW = timedelta(minutes=10)
_client_misses: dict = {}


def _client_by_phone(text: str):
    """The active client login whose userid is this phone number (last 10 digits, so +91 / 0 / spaces / dashes
    don't matter), or None."""
    digits = re.sub(r"\D", "", text or "")[-10:]
    if len(digits) != 10:
        return None
    user = User.query.filter_by(userid=digits).first()
    return user if user and user.role_key == "client" and user.is_active else None


def _client_throttled() -> bool:
    now = utcnow()
    recent = [t for t in _client_misses.get(request.remote_addr, []) if now - t < CLIENT_MISS_WINDOW]
    _client_misses[request.remote_addr] = recent
    return len(recent) >= CLIENT_MISS_LIMIT


def _note_client_miss() -> None:
    _client_misses.setdefault(request.remote_addr, []).append(utcnow())


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
    # Back to whatever page this was once signed in again (kohal, 2026-10-21: "after login and when the
    # application is switched, the app should open to the page which was open") - typically the session
    # having quietly expired while the phone had the app backgrounded, not a deliberate sign-out, so
    # landing on the admin/attendance default instead of back here would be jarring. Query string only; a
    # hash fragment never reaches the server to begin with, so a client-side reload (common.js's own 401
    # handling in api()) is what actually preserves one of those - this covers a fresh top-level GET.
    next_path = request.path
    if request.query_string:
        next_path += "?" + request.query_string.decode()
    return redirect(url_for("auth.login", next=next_path))


# ---------- pages ----------

@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = _safe_next(request.values.get("next"))
    # Purely cosmetic - "Client sign in" copy and a toggle link, same userid+PIN underneath either way
    # (kohal, 2026-10-22: "a new option while logging in asking if you are client") - a client is still
    # just a User row like any other, nothing about the credential check itself differs.
    client_mode = request.values.get("as") == "client"
    if g.user:
        return redirect(next_url or _landing_url(g.user))
    error = None
    if request.method == "POST":
        check_csrf()
        user = find_user(request.form.get("userid", ""))
        pin = request.form.get("pin", "")
        phone_client = _client_by_phone(request.form.get("userid", ""))
        if client_mode and not pin and not phone_client:
            # A client's phone number is their whole sign-in, so a number that isn't one is counted.
            if _client_throttled():
                error = LOCKED_MESSAGE
            else:
                _note_client_miss()
                error = "We couldn't find a client login for that phone number. Ask us to give you access."
        elif phone_client and not pin:
            # No PIN to check. The first time in, give the login an unguessable hash so it counts as active
            # (auth.load_user only keeps a session for someone who has a password_hash, and "Has logged in"
            # on the Clients list reads it) - nobody knows it, so the PIN form can never match it.
            if not phone_client.password_hash:
                phone_client.password_hash = generate_password_hash(secrets.token_hex(16))
            db.session.commit()
            session.clear()
            session["uid"] = phone_client.code
            session.permanent = True
            return redirect(next_url or _landing_url(phone_client))
        elif _is_locked(user):
            error = LOCKED_MESSAGE
        else:
            has_pin = bool(user and user.password_hash)
            # Always run one hash check so a wrong userid takes as long as a wrong PIN.
            matches = check_password_hash(user.password_hash if has_pin else _DUMMY_HASH, pin)
            if matches and has_pin and not user.is_active:
                error = "This account is switched off. Ask your admin."
            elif matches and has_pin:
                user.failed_attempts = 0
                # Self-heal: the employee row (work plan, wages, fooding, cash all hang off it) used to be made
                # only at first PIN setup, so anyone whose link was lost or never made stayed cut off for good.
                sync_worker_for_user(user)
                db.session.commit()
                session.clear()
                session["uid"] = user.code
                session.permanent = True
                return redirect(next_url or _landing_url(user))
            else:
                _register_failure(user)
                error = "Wrong userid or PIN."
    return render_template("login.html", error=error, userid=request.form.get("userid", ""), next=next_url,
                            client_mode=client_mode)


@bp.route("/set-pin", methods=["GET", "POST"])
def set_pin():
    if g.user:
        return redirect(_landing_url(g.user))
    client_mode = request.values.get("as") == "client"
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
                return redirect(url_for("auth.login", **({"as": "client"} if client_mode else {})))
    return render_template("set_pin.html", error=error, userid=userid, pin_length=PIN_LENGTH, client_mode=client_mode)


@bp.post("/logout")
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("auth.login"))

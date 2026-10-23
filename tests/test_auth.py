import re
from datetime import timedelta

from app.auth import MAX_FAILURES, create_user, find_user
from app.extensions import db
from app.models import User, utcnow
from conftest import PIN, csrf, make_user, signed_in


def login(client, userid, pin):
    return client.post("/login", data={"csrf": csrf(client), "userid": userid, "pin": pin})


def set_pin(client, userid, code, pin, confirm=None):
    return client.post("/set-pin", data={
        "csrf": csrf(client), "userid": userid, "code": code,
        "pin": pin, "confirm": pin if confirm is None else confirm,
    })


def pending_user(name="Newbie"):
    user, code = create_user(name)
    db.session.commit()
    return user, code


def test_everything_is_locked_until_login(anon):
    assert anon.get("/").status_code == 302
    assert anon.get("/export.csv").status_code == 302
    assert anon.get("/api/state").status_code == 401
    assert anon.get("/api/users").status_code == 401
    assert anon.get("/login").status_code == 200
    assert anon.get("/set-pin").status_code == 200


def test_wrong_and_right_pin(app, user, anon):
    bad = login(anon, user.userid, "000000")
    assert bad.status_code == 200 and b"Wrong userid or PIN" in bad.data
    unknown = login(anon, "ghost-1234", PIN)
    assert b"Wrong userid or PIN" in unknown.data
    ok = login(anon, user.userid.upper(), PIN)              # userid is not case sensitive
    assert ok.status_code == 302
    me = anon.get("/api/state").get_json()["me"]
    assert me == {"userid": user.userid, "name": "Tester", "is_admin": False, "modules": ["leads", "attendance"]}


def test_login_lands_the_admin_on_me_and_everyone_else_on_attendance(app, anon, user):
    """kohal, 2026-10-21: "make admin landing page as me tab and other landing pages as attendnace tab" -
    the Leads tab itself is unaffected, still "/" (views.index), same as always - this is only about where
    signing in itself sends someone."""
    admin = make_user("Landing Admin", is_admin=True, pin="193857")
    ok = login(anon, admin.userid, "193857")
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/me")

    other = app.test_client()   # a second, still-anonymous client - `anon` is now the admin's own session
    ok2 = login(other, user.userid, PIN)
    assert ok2.status_code == 302 and ok2.headers["Location"].endswith("/attendance")


# ---------- a client role lands on its own portal, not Attendance (kohal, 2026-10-22) ----------

def test_login_lands_a_client_on_their_own_portal(app, anon):
    from app.models import Client
    with app.app_context():
        c = Client(name="Kalyani Cold Storage")
        db.session.add(c)
        db.session.commit()
        who = make_user("Kalyani Contact", pin="482917", role="client")
        who.client_id = c.id
        db.session.commit()
        userid = who.userid
    ok = login(anon, userid, "482917")
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/my-projects")


def test_a_client_can_sign_in_with_their_own_phone_number_end_to_end(app, admin_client, anon):
    """kohal, 2026-10-23: "the login of client should be mapped to its mobile number... so number will be
    the mapping key" - the full real flow: admin gives login access, the client sets their PIN using their
    phone number as the userid, then signs in with it."""
    from app.models import Client
    with app.app_context():
        c = Client(name="Kalyani Cold Storage", phone="9876543210")
        db.session.add(c)
        db.session.commit()
        cid = c.id
    given = admin_client.post(f"/api/clients/{cid}/login").get_json()
    userid = given["user"]["userid"]
    assert userid == "9876543210"

    done = set_pin(anon, userid, given["setup_code"], "482917")
    assert done.status_code == 302

    ok = login(app.test_client(), userid, "482917")
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/my-projects")


def test_login_and_set_pin_show_client_mode_copy_when_asked(anon):
    """kohal, 2026-10-22: "a new option while logging in asking if you are client" - cosmetic only, the
    same userid+PIN (or userid+code+PIN) underneath either way."""
    login_html = anon.get("/login?as=client").get_data(as_text=True)
    assert "Client sign in" in login_html and 'name="as" value="client"' in login_html
    assert "Staff sign in instead" in login_html

    staff_html = anon.get("/login").get_data(as_text=True)
    assert "Are you a client?" in staff_html

    set_pin_html = anon.get("/set-pin?as=client").get_data(as_text=True)
    assert "Set your client PIN" in set_pin_html


# ---------- returning to where you were (kohal, 2026-10-21) ----------
#
# "after login and when the application is switched, the app should open to the page which was open" -
# the session quietly expiring while the phone had the app backgrounded is the common case this covers,
# not a deliberate sign-out (see auth.logout, unaffected - that one's a real "leave" with nothing to
# return to).

def test_visiting_a_protected_page_signed_out_preserves_where_to_return_to(anon):
    res = anon.get("/projects")
    assert res.status_code == 302
    assert res.headers["Location"] == "/login?next=/projects"


def test_login_page_carries_next_through_as_a_hidden_field(anon):
    html = anon.get("/login?next=/projects").get_data(as_text=True)
    assert 'name="next" value="/projects"' in html


def test_logging_in_with_a_next_returns_there_instead_of_the_usual_landing_page(anon):
    admin = make_user("Next Admin", is_admin=True, pin="193857")
    res = anon.post("/login", data={"csrf": csrf(anon), "userid": admin.userid, "pin": "193857", "next": "/projects"})
    assert res.status_code == 302 and res.headers["Location"] == "/projects"


def test_an_absolute_url_as_next_is_ignored(anon):
    admin = make_user("Safe Admin", is_admin=True, pin="193857")
    res = anon.post("/login", data={
        "csrf": csrf(anon), "userid": admin.userid, "pin": "193857", "next": "https://evil.example/phish",
    })
    assert res.status_code == 302 and res.headers["Location"].endswith("/me")


def test_a_protocol_relative_next_is_ignored(anon):
    """//evil.example looks relative (no scheme) but a browser treats it as "same scheme, different host" -
    still off-site, so it's refused the same as a full https:// one."""
    admin = make_user("Safer Admin", is_admin=True, pin="193857")
    res = anon.post("/login", data={
        "csrf": csrf(anon), "userid": admin.userid, "pin": "193857", "next": "//evil.example/phish",
    })
    assert res.status_code == 302 and res.headers["Location"].endswith("/me")


def test_login_needs_csrf(anon, user):
    assert anon.post("/login", data={"userid": user.userid, "pin": PIN}).status_code == 400


def test_repeated_wrong_pins_lock_the_account(app, user, anon):
    for _ in range(MAX_FAILURES):
        login(anon, user.userid, "999000")
    locked = login(anon, user.userid, PIN)                    # even the right PIN is refused
    assert b"Too many wrong tries" in locked.data
    user.locked_until = utcnow() - timedelta(seconds=1)            # lock runs out
    db.session.commit()
    assert login(anon, user.userid, PIN).status_code == 302


def test_logout(client):
    assert client.get("/api/state").status_code == 200
    assert client.post("/logout", data={"csrf": csrf(client)}).status_code == 302
    assert client.get("/api/state").status_code == 401


# ---------- userid and setup code ----------

def test_userid_is_name_plus_unique_four_digit_code(app):
    a, _ = create_user("Ravi Kumar")
    b, _ = create_user("Ravi Kumar")
    db.session.commit()
    assert re.fullmatch(r"ravikumar-\d{4}", a.userid) and a.userid.endswith(a.code)
    assert re.fullmatch(r"\d{4}", a.code) and 1000 <= int(a.code) <= 9999
    assert a.code != b.code and a.userid != b.userid
    assert find_user(a.userid) is a and find_user("someoneelse-" + b.code) is None and find_user(b.userid.upper()) is b


def test_create_user_can_take_an_explicit_userid(app):
    """kohal, 2026-10-23: "so number will be the mapping key" - give_login (app/clients.py) uses this to
    make a client's userid their own phone number instead of the usual name-code."""
    user, _ = create_user("Kalyani Contact", role="client", userid="9876543210")
    db.session.commit()
    assert user.userid == "9876543210"
    assert find_user("9876543210") is user              # find_user works with no dash at all now

    try:
        create_user("Someone Else", role="client", userid="9876543210")
    except ValueError as err:
        assert "already used" in str(err)
    else:
        raise AssertionError("expected ValueError")


def test_userid_forgives_stray_whitespace_and_smart_dashes(app):
    # A phone keyboard can slip a space around the dash, or autocorrect it to an en/em dash, without
    # the person noticing - none of that should read as a wrong userid.
    a, _ = create_user("Ravi Kumar")
    db.session.commit()
    name, code = a.userid.split("-")
    assert find_user(f"{name} - {code}") is a
    assert find_user(f"{name}–{code}") is a
    assert find_user(f"{name}—{code}") is a
    assert find_user(f" {a.userid} ") is a


def test_name_needs_letters_or_numbers(app):
    try:
        create_user("   !!!  ")
    except ValueError as err:
        assert "letters or numbers" in str(err)
    else:
        raise AssertionError("expected ValueError")


def test_new_user_sets_pin_with_setup_code_once(app, anon):
    user, code = pending_user()
    assert user.status == "pending"
    assert login(anon, user.userid, "135790").status_code == 200        # no PIN yet

    done = set_pin(anon, user.userid, code.lower(), "731905")     # code is forgiving on case
    assert done.status_code == 302 and done.headers["Location"].endswith("/login")
    assert login(anon, user.userid, "731905").status_code == 302

    again = set_pin(app.test_client(), user.userid, code, "264018")   # single use
    assert again.status_code == 200 and b"do not match" in again.data
    assert db.session.get(User, user.code).setup_code_hash is None


def test_setup_code_rules(app, anon):
    user, code = pending_user()
    assert b"do not match" in set_pin(anon, user.userid, "WRONG-CODE", "731905").data
    assert b"exactly 6 digits" in set_pin(anon, user.userid, code, "7319").data          # too short
    assert b"exactly 6 digits" in set_pin(anon, user.userid, code, "73190512").data      # too long
    assert b"exactly 6 digits" in set_pin(anon, user.userid, code, "73190a").data        # letters
    assert b"different" in set_pin(anon, user.userid, code, "731905", "731906").data

    user.setup_code_expires = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert b"expired" in set_pin(anon, user.userid, code, "731905").data


def test_setup_code_starts_with_the_persons_own_name(app):
    """kohal, 2026-10-15: the first 4 characters are built from the person's name, so the code visibly
    belongs to them instead of reading as a random string - see auth._name_prefix."""
    user, code = pending_user("Imtyaz Alarm Contractor")
    assert code.split("-")[0] == "IMTY"
    assert len(code.replace("-", "")) == 8

    _, short_code = pending_user("Jo")     # fewer than 4 letters - padded out, not left ambiguous
    prefix = short_code.split("-")[0]
    assert len(prefix) == 4 and prefix.startswith("JO")


def test_obvious_pins_are_refused(app, anon):
    user, code = pending_user()
    for weak in ("111111", "000000", "123456", "654321", "234567", "987654"):
        assert b"repeated digit" in set_pin(anon, user.userid, code, weak).data, weak
    assert set_pin(anon, user.userid, code, "135790").status_code == 302                  # not a run, so fine


def test_wrong_setup_codes_lock_guessing(app, anon):
    user, code = pending_user()
    for _ in range(MAX_FAILURES):
        set_pin(anon, user.userid, "AAAA-AAAA", "731905")
    assert b"Too many wrong tries" in set_pin(anon, user.userid, code, "731905").data


# ---------- reset, switch off ----------

def test_admin_reset_lets_the_user_choose_a_new_pin(app, admin_client, anon):
    user = make_user("Sita")
    session_client = signed_in(app, user)
    assert session_client.get("/api/state").status_code == 200

    res = admin_client.post(f"/api/users/{user.code}/reset", json={})
    code = res.get_json()["setup_code"]
    assert res.status_code == 200 and res.get_json()["user"]["status"] == "pending"

    assert session_client.get("/api/state").status_code == 401                   # old session ended
    assert login(anon, user.userid, PIN).status_code == 200                 # old PIN is dead
    assert set_pin(anon, user.userid, code, "586142").status_code == 302
    assert login(anon, user.userid, "586142").status_code == 302


def test_switched_off_user_is_locked_out_and_can_be_switched_back_on(app, admin_client, anon):
    user = make_user("Kiran")
    session_client = signed_in(app, user)
    off = admin_client.post(f"/api/users/{user.code}/active", json={"active": False})
    assert off.get_json()["user"]["status"] == "off"
    assert session_client.get("/api/state").status_code == 401
    assert b"switched off" in login(anon, user.userid, PIN).data
    admin_client.post(f"/api/users/{user.code}/active", json={"active": True})
    assert login(anon, user.userid, PIN).status_code == 302

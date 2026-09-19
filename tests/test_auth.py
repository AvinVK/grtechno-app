import re
from datetime import timedelta

from app.auth import MAX_FAILURES, create_user, find_user
from app.extensions import db
from app.models import User, utcnow
from conftest import PASSWORD, csrf, make_user, signed_in


def login(client, userid, password):
    return client.post("/login", data={"csrf": csrf(client), "userid": userid, "password": password})


def set_password(client, userid, code, password, confirm=None):
    return client.post("/set-password", data={
        "csrf": csrf(client), "userid": userid, "code": code,
        "password": password, "confirm": password if confirm is None else confirm,
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
    assert anon.get("/set-password").status_code == 200


def test_wrong_and_right_password(app, user, anon):
    bad = login(anon, user.userid, "nope")
    assert bad.status_code == 200 and b"Wrong userid or password" in bad.data
    unknown = login(anon, "ghost-1234", PASSWORD)
    assert b"Wrong userid or password" in unknown.data
    ok = login(anon, user.userid.upper(), PASSWORD)              # userid is not case sensitive
    assert ok.status_code == 302
    me = anon.get("/api/state").get_json()["me"]
    assert me == {"userid": user.userid, "name": "Tester", "is_admin": False}


def test_login_needs_csrf(anon, user):
    assert anon.post("/login", data={"userid": user.userid, "password": PASSWORD}).status_code == 400


def test_repeated_wrong_passwords_lock_the_account(app, user, anon):
    for _ in range(MAX_FAILURES):
        login(anon, user.userid, "wrong")
    locked = login(anon, user.userid, PASSWORD)                    # even the right password is refused
    assert b"Too many wrong tries" in locked.data
    user.locked_until = utcnow() - timedelta(seconds=1)            # lock runs out
    db.session.commit()
    assert login(anon, user.userid, PASSWORD).status_code == 302


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


def test_name_needs_letters_or_numbers(app):
    try:
        create_user("   !!!  ")
    except ValueError as err:
        assert "letters or numbers" in str(err)
    else:
        raise AssertionError("expected ValueError")


def test_new_user_sets_password_with_setup_code_once(app, anon):
    user, code = pending_user()
    assert user.status == "pending"
    assert login(anon, user.userid, "anything-at-all").status_code == 200        # no password yet

    done = set_password(anon, user.userid, code.lower(), "brand-new-secret")     # code is forgiving on case
    assert done.status_code == 302 and done.headers["Location"].endswith("/login")
    assert login(anon, user.userid, "brand-new-secret").status_code == 302

    again = set_password(app.test_client(), user.userid, code, "another-secret-1")   # single use
    assert again.status_code == 200 and b"do not match" in again.data
    assert db.session.get(User, user.code).setup_code_hash is None


def test_setup_code_rules(app, anon):
    user, code = pending_user()
    assert b"do not match" in set_password(anon, user.userid, "WRONG-CODE", "long-enough-pw").data
    assert b"at least 8" in set_password(anon, user.userid, code, "short").data
    assert b"different" in set_password(anon, user.userid, code, "long-enough-pw", "long-enough-px").data
    assert b"not your name" in set_password(anon, user.userid, code, user.userid).data

    user.setup_code_expires = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert b"expired" in set_password(anon, user.userid, code, "long-enough-pw").data


def test_wrong_setup_codes_lock_guessing(app, anon):
    user, code = pending_user()
    for _ in range(MAX_FAILURES):
        set_password(anon, user.userid, "AAAA-AAAA", "long-enough-pw")
    assert b"Too many wrong tries" in set_password(anon, user.userid, code, "long-enough-pw").data


# ---------- reset, switch off ----------

def test_admin_reset_lets_the_user_choose_a_new_password(app, admin_client, anon):
    user = make_user("Sita")
    session_client = signed_in(app, user)
    assert session_client.get("/api/state").status_code == 200

    res = admin_client.post(f"/api/users/{user.code}/reset", json={})
    code = res.get_json()["setup_code"]
    assert res.status_code == 200 and res.get_json()["user"]["status"] == "pending"

    assert session_client.get("/api/state").status_code == 401                   # old session ended
    assert login(anon, user.userid, PASSWORD).status_code == 200                 # old password is dead
    assert set_password(anon, user.userid, code, "a-fresh-password").status_code == 302
    assert login(anon, user.userid, "a-fresh-password").status_code == 302


def test_switched_off_user_is_locked_out_and_can_be_switched_back_on(app, admin_client, anon):
    user = make_user("Kiran")
    session_client = signed_in(app, user)
    off = admin_client.post(f"/api/users/{user.code}/active", json={"active": False})
    assert off.get_json()["user"]["status"] == "off"
    assert session_client.get("/api/state").status_code == 401
    assert b"switched off" in login(anon, user.userid, PASSWORD).data
    admin_client.post(f"/api/users/{user.code}/active", json={"active": True})
    assert login(anon, user.userid, PASSWORD).status_code == 302

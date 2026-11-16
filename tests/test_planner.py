"""The admin's meeting planner and scheduler (kohal, 2026-11-16) - meetings with the fields of his meeting sheet, to-do tasks, the manual time, the
auto scheduler that fills free slots around it, and the follow-up a "next schedule plan" creates by itself."""

from datetime import date, timedelta

from app.extensions import db
from app.models import Client, PlannerMeeting


def _day(n=10):
    return (date.today() + timedelta(days=n)).isoformat()


def _meeting(c, **over):
    body = {"client_name": "Kalyani Warehousing", "address": "Kamptee Road godown", "contact_no": "9800000001", "purpose": "Fire NOC discussion",
            "place": "Site office", "meeting_date": _day(), **over}
    r = c.post("/api/planner/meetings", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["meeting"]


def _task(c, **over):
    r = c.post("/api/planner/tasks", json={"title": "Call the fire officer", "task_date": _day(), **over})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["task"]


def _day_view(c, day=None):
    return c.get(f"/api/planner/day?date={day or _day()}").get_json()


def test_only_the_admin_can_use_the_planner(client, manager_client, admin_client, anon):
    for c in (client, manager_client):
        assert c.get("/planner").status_code == 403
        assert c.get("/api/planner/day").status_code == 403
        assert c.post("/api/planner/meetings", json={"client_name": "X", "purpose": "Y", "meeting_date": _day()}).status_code == 403
        assert c.post("/api/planner/arrange", json={"date": _day()}).status_code == 403
    assert anon.get("/api/planner/day").status_code in (401, 302)
    assert admin_client.get("/planner").status_code == 200


def test_a_meeting_keeps_every_field_of_the_meeting_sheet(admin_client):
    m = _meeting(admin_client, meeting_time="11:30", duration_min=90)
    assert abs((date.fromisoformat(m["logged_on"]) - date.today()).days) <= 1                          # the sheet's "Date": the day it was entered
    assert (m["client_name"], m["address"], m["contact_no"]) == ("Kalyani Warehousing", "Kamptee Road godown", "9800000001")
    assert (m["purpose"], m["place"], m["meeting_time"], m["duration_min"], m["status"]) == ("Fire NOC discussion", "Site office", "11:30", 90, "planned")
    saved = _day_view(admin_client)["meetings"][0]
    assert saved["id"] == m["id"] and saved["contact_no"] == "9800000001"
    r = admin_client.patch(f"/api/planner/meetings/{m['id']}", json={"status": "done", "remark": "Agreed to go ahead, wants a revised quote"})
    assert r.get_json()["meeting"]["status"] == "done" and "revised quote" in r.get_json()["meeting"]["remark"]


def test_a_meeting_is_a_client_meeting_or_a_call_and_a_task_a_site_visit_or_work(admin_client):
    """The four categories (kohal, 2026-11-16): client meeting and call to make are meetings; site visit and work to do are tasks."""
    assert _meeting(admin_client)["kind"] == "client_meeting" and _task(admin_client)["kind"] == "site_visit"       # what you get unless you pick
    call = _meeting(admin_client, kind="call", client_name="Ring me back")
    work = _task(admin_client, kind="work", title="Prepare the AMC quotation")
    assert call["kind"] == "call" and work["kind"] == "work"
    day = _day_view(admin_client)
    assert {m["client_name"]: m["kind"] for m in day["meetings"]}["Ring me back"] == "call"
    assert {t["title"]: t["kind"] for t in day["tasks"]}["Prepare the AMC quotation"] == "work"
    assert admin_client.patch(f"/api/planner/meetings/{call['id']}", json={"kind": "client_meeting"}).get_json()["meeting"]["kind"] == "client_meeting"
    assert admin_client.patch(f"/api/planner/tasks/{work['id']}", json={"kind": "site_visit"}).get_json()["task"]["kind"] == "site_visit"
    for bad in ("site_visit", "work", "lunch"):                                  # a task's kind is not a meeting's, and the other way round
        r = admin_client.post("/api/planner/meetings", json={"client_name": "A", "purpose": "B", "meeting_date": _day(), "kind": bad})
        assert r.status_code == 422 and "kind" in r.get_json()["fields"]
    for bad in ("call", "client_meeting", "lunch"):
        r = admin_client.post("/api/planner/tasks", json={"title": "A", "task_date": _day(), "kind": bad})
        assert r.status_code == 422 and "kind" in r.get_json()["fields"]


def test_a_follow_up_of_a_call_is_a_call(admin_client):
    first = _meeting(admin_client, kind="call", next_plan="Ring again", next_date=_day(9))
    assert _day_view(admin_client, _day(9))["meetings"][0]["kind"] == "call" and first["kind"] == "call"


def test_a_meeting_needs_a_client_a_purpose_and_a_date(admin_client):
    r = admin_client.post("/api/planner/meetings", json={})
    assert r.status_code == 422
    assert {"client_name", "purpose", "meeting_date"} <= set(r.get_json()["fields"])
    r = admin_client.post("/api/planner/meetings", json={"client_name": "A", "purpose": "B", "meeting_date": _day(), "meeting_time": "25:99"})
    assert r.status_code == 422 and "meeting_time" in r.get_json()["fields"]
    r = admin_client.post("/api/planner/meetings", json={"client_name": "A", "purpose": "B", "meeting_date": "tomorrow"})
    assert r.status_code == 422 and "meeting_date" in r.get_json()["fields"]
    assert admin_client.patch("/api/planner/meetings/9999", json={"remark": "x"}).status_code == 404


def test_the_me_tab_has_a_planner_tile_for_the_admin_only_and_no_projects_tile(app, admin_client, manager_client):
    html = admin_client.get("/me").get_data(as_text=True)
    assert 'class="me-tile" href="/planner"' in html
    assert 'class="me-tile" href="/projects"' not in html                    # the Projects tab is the same page (kohal, 2026-11-16)
    _meeting(admin_client, meeting_date=date.today().isoformat())
    assert "meeting" in admin_client.get("/me").get_data(as_text=True).split('href="/planner"')[1].split("</a>")[0]
    assert "/planner" not in manager_client.get("/me").get_data(as_text=True)


def test_an_existing_client_can_fill_the_meeting_in(app, admin_client):
    with app.app_context():
        db.session.add(Client(name="Orange City Hospital", phone="9811111111", address="Civil Lines", city="Nagpur"))
        db.session.commit()
    listed = admin_client.get("/api/planner/clients").get_json()["clients"]
    assert listed[0]["name"] == "Orange City Hospital" and listed[0]["contact_no"] == "9811111111" and listed[0]["address"] == "Civil Lines, Nagpur"
    m = _meeting(admin_client, client_id=listed[0]["id"], client_name="Orange City Hospital")
    assert m["client_id"] == listed[0]["id"]
    r = admin_client.post("/api/planner/meetings", json={"client_name": "A", "purpose": "B", "meeting_date": _day(), "client_id": 9999})
    assert r.status_code == 422 and "client_id" in r.get_json()["fields"]


def test_manual_times_order_the_day_and_a_clash_is_flagged(admin_client):
    late = _meeting(admin_client, client_name="Late one", meeting_time="15:00")
    first = _meeting(admin_client, client_name="First one", meeting_time="10:00", duration_min=60)
    overlapping = _task(admin_client, task_time="10:30", duration_min=30)
    day = _day_view(admin_client)
    assert [m["id"] for m in day["meetings"]] == [first["id"], late["id"]]
    assert {m["id"]: m["clash"] for m in day["meetings"]} == {first["id"]: True, late["id"]: False}
    assert day["tasks"][0]["id"] == overlapping["id"] and day["tasks"][0]["clash"] is True
    admin_client.patch(f"/api/planner/meetings/{first['id']}", json={"status": "cancelled"})          # a cancelled meeting no longer holds its slot
    assert not any(x["clash"] for x in _day_view(admin_client)["meetings"] + _day_view(admin_client)["tasks"])


def test_the_auto_scheduler_fills_free_slots_and_never_moves_a_time_set_by_hand(admin_client):
    fixed = _meeting(admin_client, client_name="Fixed", meeting_time="09:00", duration_min=60)       # 9:00-10:00
    a = _meeting(admin_client, client_name="A")                                                       # no time, an hour
    b = _meeting(admin_client, client_name="B", duration_min=30)
    t = _task(admin_client, duration_min=30)
    r = admin_client.post("/api/planner/arrange", json={"date": _day()})
    out = r.get_json()
    assert (out["placed"], out["left"]) == (3, 0)
    times = {m["client_name"]: m["meeting_time"] for m in out["meetings"]}
    assert times["Fixed"] == "09:00"                                                                  # untouched
    assert times["A"] == "10:15"                                                                      # right after Fixed plus the 15-minute gap
    assert times["B"] == "11:30"                                                                      # after A (ends 11:15) plus the gap
    assert out["tasks"][0]["task_time"] == "12:15"                                                    # tasks go after the meetings
    assert not any(x["clash"] for x in out["meetings"] + out["tasks"])
    again = admin_client.post("/api/planner/arrange", json={"date": _day()}).get_json()
    assert (again["placed"], again["left"]) == (0, 0)                                                 # nothing left to place, nothing moves
    assert {m["id"]: m["meeting_time"] for m in again["meetings"]}[fixed["id"]] == "09:00"
    assert a["id"] and b["id"] and t["id"]


def test_the_auto_scheduler_fits_around_a_meeting_in_the_middle_of_the_day(admin_client):
    _meeting(admin_client, client_name="Midday", meeting_time="09:30", duration_min=60)            # leaves 9:00-9:15 only: too short for an hour
    _meeting(admin_client, client_name="Placed")
    out = admin_client.post("/api/planner/arrange", json={"date": _day()}).get_json()
    assert {m["client_name"]: m["meeting_time"] for m in out["meetings"]}["Placed"] == "10:45"


def test_what_does_not_fit_before_seven_in_the_evening_is_left_for_the_admin(admin_client):
    _meeting(admin_client, client_name="Long", meeting_time="09:00", duration_min=180)
    _meeting(admin_client, client_name="Long 2", meeting_time="12:15", duration_min=180)
    _meeting(admin_client, client_name="Long 3", meeting_time="15:30", duration_min=180)             # ends 18:30
    _meeting(admin_client, client_name="Won't fit", duration_min=60)
    out = admin_client.post("/api/planner/arrange", json={"date": _day()}).get_json()
    assert (out["placed"], out["left"]) == (0, 1)
    assert {m["client_name"]: m["meeting_time"] for m in out["meetings"]}["Won't fit"] is None


def test_arrange_all_upcoming_covers_every_day_with_something_waiting(admin_client):
    _meeting(admin_client, client_name="Day 3", meeting_date=_day(3))
    _meeting(admin_client, client_name="Day 5", meeting_date=_day(5))
    _task(admin_client, task_date=_day(7))
    out = admin_client.post("/api/planner/arrange", json={"upcoming": True}).get_json()
    assert (out["placed"], out["left"]) == (3, 0)
    assert _day_view(admin_client, _day(3))["meetings"][0]["meeting_time"] == "09:00"
    assert _day_view(admin_client, _day(7))["tasks"][0]["task_time"] == "09:00"


def test_a_next_plan_with_a_date_creates_the_follow_up_and_places_it(admin_client):
    first = _meeting(admin_client, meeting_date=_day(2), next_plan="Send the revised quote", next_date=_day(9))
    follow = [m for m in _day_view(admin_client, _day(9))["meetings"] if m["follow_up_of_id"] == first["id"]]
    assert len(follow) == 1
    f = follow[0]
    assert (f["client_name"], f["address"], f["purpose"], f["status"]) == ("Kalyani Warehousing", "Kamptee Road godown", "Send the revised quote", "planned")
    assert f["meeting_time"] == "09:00"                                                               # auto-placed into the first free slot
    other = _meeting(admin_client, client_name="Same day", meeting_date=_day(9), meeting_time="09:00")
    moved = admin_client.patch(f"/api/planner/meetings/{first['id']}", json={"next_date": _day(11)}).get_json()["meeting"]
    assert moved["next_date"] == _day(11)
    again = [m for m in _day_view(admin_client, _day(11))["meetings"] if m["follow_up_of_id"] == first["id"]]
    assert len(again) == 1 and again[0]["id"] == f["id"] and again[0]["meeting_time"] == "09:00"      # the same meeting, moved to its new day and re-placed
    assert all(m["id"] != f["id"] for m in _day_view(admin_client, _day(9))["meetings"])
    assert other["id"]


def test_saving_other_fields_does_not_disturb_a_follow_up_the_admin_adjusted(admin_client):
    first = _meeting(admin_client, next_plan="Visit the site", next_date=_day(9))
    follow = [m for m in _day_view(admin_client, _day(9))["meetings"]][0]
    admin_client.patch(f"/api/planner/meetings/{follow['id']}", json={"meeting_time": "16:00", "purpose": "Site visit with the engineer"})
    admin_client.patch(f"/api/planner/meetings/{first['id']}", json={"remark": "Went well"})
    after = _day_view(admin_client, _day(9))["meetings"][0]
    assert (after["meeting_time"], after["purpose"]) == ("16:00", "Site visit with the engineer")


def test_clearing_the_next_date_cancels_a_follow_up_that_is_still_only_planned(admin_client):
    first = _meeting(admin_client, next_plan="Call back", next_date=_day(9))
    admin_client.patch(f"/api/planner/meetings/{first['id']}", json={"next_date": None})
    assert _day_view(admin_client, _day(9))["meetings"][0]["status"] == "cancelled"
    held = _meeting(admin_client, client_name="Held", next_plan="Again", next_date=_day(12))
    follow = _day_view(admin_client, _day(12))["meetings"][0]
    admin_client.patch(f"/api/planner/meetings/{follow['id']}", json={"status": "done"})
    admin_client.patch(f"/api/planner/meetings/{held['id']}", json={"next_date": None})
    assert _day_view(admin_client, _day(12))["meetings"][0]["status"] == "done"                      # one that took place is never touched


def test_moving_a_meeting_to_another_day_clears_its_time_so_it_finds_a_new_slot(admin_client):
    m = _meeting(admin_client, meeting_time="14:00")
    moved = admin_client.patch(f"/api/planner/meetings/{m['id']}", json={"meeting_date": _day(12)}).get_json()["meeting"]
    assert moved["meeting_time"] is None
    kept = admin_client.patch(f"/api/planner/meetings/{m['id']}", json={"meeting_date": _day(13), "meeting_time": "16:00"}).get_json()["meeting"]
    assert kept["meeting_time"] == "16:00"


def test_upcoming_lists_what_is_ahead_and_what_still_needs_a_remark(app, admin_client):
    ahead = _meeting(admin_client, client_name="Ahead", meeting_date=_day(4))
    _meeting(admin_client, client_name="Cancelled", meeting_date=_day(5))
    admin_client.patch(f"/api/planner/meetings/{_day_view(admin_client, _day(5))['meetings'][0]['id']}", json={"status": "cancelled"})
    past = _meeting(admin_client, client_name="Past", meeting_date=_day(-3))                           # logging a meeting that already happened is allowed
    r = admin_client.get("/api/planner/upcoming").get_json()
    assert [m["id"] for m in r["meetings"]] == [ahead["id"]]
    assert [m["id"] for m in r["needs_remark"]] == [past["id"]]
    admin_client.patch(f"/api/planner/meetings/{past['id']}", json={"status": "done", "remark": "Done"})
    assert admin_client.get("/api/planner/upcoming").get_json()["needs_remark"] == []


def test_tasks_can_be_ticked_moved_and_removed(admin_client):
    t = _task(admin_client)
    done = admin_client.patch(f"/api/planner/tasks/{t['id']}", json={"done": True}).get_json()["task"]
    assert done["done"] is True
    assert admin_client.patch(f"/api/planner/tasks/{t['id']}", json={"done": "yes"}).status_code == 422
    assert admin_client.post("/api/planner/tasks", json={"task_date": _day()}).status_code == 422
    admin_client.patch(f"/api/planner/tasks/{t['id']}", json={"task_time": "10:00"})
    moved = admin_client.patch(f"/api/planner/tasks/{t['id']}", json={"task_date": _day(12)}).get_json()["task"]
    assert moved["task_time"] is None                                                                  # a moved task has to find a new slot too
    assert admin_client.delete(f"/api/planner/tasks/{t['id']}").status_code == 204
    assert admin_client.delete(f"/api/planner/tasks/{t['id']}").status_code == 404
    assert _day_view(admin_client, _day(12))["tasks"] == []


def test_a_finished_task_does_not_get_a_slot_from_the_auto_scheduler(admin_client):
    t = _task(admin_client)
    admin_client.patch(f"/api/planner/tasks/{t['id']}", json={"done": True})
    out = admin_client.post("/api/planner/arrange", json={"date": _day()}).get_json()
    assert out["placed"] == 0 and out["tasks"][0]["task_time"] is None


def test_the_contact_and_address_are_stored_encrypted(app, admin_client):
    m = _meeting(admin_client)
    with app.app_context():
        raw = db.session.execute(db.text("select address, contact_no from planner_meetings where id = :i"), {"i": m["id"]}).one()
        assert "9800000001" not in raw[1] and "Kamptee" not in raw[0]
        assert db.session.get(PlannerMeeting, m["id"]).contact_no == "9800000001"

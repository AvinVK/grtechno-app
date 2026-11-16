"""The admin's meeting planner (kohal, 2026-11-16) - meetings and calls with the fields of his meeting sheet, site visits and work to do, tiles he drags into
the order he wants, the follow-up a "next schedule plan" creates by itself, and the list of what was held."""

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


def _order(c, day=None):
    """The day's tiles as [kind, id] in the order they are shown."""
    return _day_view(c, day)["order"]


def test_only_the_admin_can_use_the_planner(client, manager_client, admin_client, anon):
    for c in (client, manager_client):
        assert c.get("/planner").status_code == 403
        assert c.get("/api/planner/day").status_code == 403
        assert c.post("/api/planner/meetings", json={"client_name": "X", "purpose": "Y", "meeting_date": _day()}).status_code == 403
        assert c.post("/api/planner/order", json={"date": _day(), "items": []}).status_code == 403
    assert anon.get("/api/planner/day").status_code in (401, 302)
    assert admin_client.get("/planner").status_code == 200


def test_a_meeting_keeps_every_field_of_the_meeting_sheet(admin_client):
    m = _meeting(admin_client, meeting_time="11:30")
    assert abs((date.fromisoformat(m["logged_on"]) - date.today()).days) <= 1                          # the sheet's "Date": the day it was entered
    assert (m["client_name"], m["address"], m["contact_no"]) == ("Kalyani Warehousing", "Kamptee Road godown", "9800000001")
    assert (m["purpose"], m["place"], m["meeting_time"], m["status"]) == ("Fire NOC discussion", "Site office", "11:30", "planned")
    assert "duration_min" not in m                                                                    # how long is no longer asked
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


def test_new_tiles_join_the_end_of_the_day_meetings_and_tasks_in_one_order(admin_client):
    a = _meeting(admin_client, client_name="A")
    t = _task(admin_client)
    b = _meeting(admin_client, client_name="B", meeting_time="08:00")                                  # a time is a label - it does not move the tile up
    assert _order(admin_client) == [["meeting", a["id"]], ["task", t["id"]], ["meeting", b["id"]]]
    assert [m["position"] for m in _day_view(admin_client)["meetings"]] == [0, 2]
    assert _order(admin_client, _day(11)) == []


def test_dragging_tiles_saves_the_order_across_meetings_and_tasks(admin_client):
    a, b = _meeting(admin_client, client_name="A"), _meeting(admin_client, client_name="B")
    t = _task(admin_client)
    want = [["task", t["id"]], ["meeting", b["id"]], ["meeting", a["id"]]]
    r = admin_client.post("/api/planner/order", json={"date": _day(), "items": want})
    assert r.status_code == 200 and r.get_json()["order"] == want
    assert _order(admin_client) == want                                                               # and it is what the day shows next time
    c = _meeting(admin_client, client_name="C")                                                       # a tile added afterwards goes last
    assert _order(admin_client)[-1] == ["meeting", c["id"]]


def test_a_tile_left_out_of_the_new_order_keeps_a_place_after_the_listed_ones(admin_client):
    a, b, c = (_meeting(admin_client, client_name=n) for n in "ABC")
    admin_client.post("/api/planner/order", json={"date": _day(), "items": [["meeting", c["id"]], ["meeting", a["id"]]]})
    assert _order(admin_client) == [["meeting", c["id"]], ["meeting", a["id"]], ["meeting", b["id"]]]


def test_the_order_must_name_real_tiles_of_that_day_once_each(admin_client):
    a = _meeting(admin_client)
    elsewhere = _meeting(admin_client, meeting_date=_day(11))
    url = "/api/planner/order"
    assert admin_client.post(url, json={"date": _day(), "items": "nope"}).status_code == 422
    assert admin_client.post(url, json={"date": _day(), "items": [["meeting", elsewhere["id"]]]}).status_code == 422       # another day's tile
    assert admin_client.post(url, json={"date": _day(), "items": [["meeting", 9999]]}).status_code == 422
    assert admin_client.post(url, json={"date": _day(), "items": [["lunch", a["id"]]]}).status_code == 422
    assert admin_client.post(url, json={"date": _day(), "items": [["meeting", str(a["id"])]]}).status_code == 422
    assert admin_client.post(url, json={"date": _day(), "items": [["meeting", True]]}).status_code == 422
    assert admin_client.post(url, json={"date": _day(), "items": [["meeting", a["id"]], ["meeting", a["id"]]]}).status_code == 422
    assert admin_client.post(url, json={"date": "soon", "items": []}).status_code == 422
    assert _order(admin_client, _day(11)) == [["meeting", elsewhere["id"]]]                          # nothing moved


def test_a_clash_is_flagged_for_two_tiles_at_the_same_time_but_a_cancelled_meeting_holds_no_time(admin_client):
    first = _meeting(admin_client, client_name="First one", meeting_time="10:00")
    late = _meeting(admin_client, client_name="Late one", meeting_time="15:00")
    overlapping = _task(admin_client, task_time="10:00")
    day = _day_view(admin_client)
    assert {m["id"]: m["clash"] for m in day["meetings"]} == {first["id"]: True, late["id"]: False}
    assert day["tasks"][0]["id"] == overlapping["id"] and day["tasks"][0]["clash"] is True
    admin_client.patch(f"/api/planner/meetings/{first['id']}", json={"status": "cancelled"})
    after = _day_view(admin_client)
    assert not any(x["clash"] for x in after["meetings"] + after["tasks"])


def test_moving_a_tile_to_another_day_puts_it_last_there_and_keeps_its_time(admin_client):
    other = _meeting(admin_client, client_name="Already there", meeting_date=_day(12))
    m = _meeting(admin_client, meeting_time="14:00")
    moved = admin_client.patch(f"/api/planner/meetings/{m['id']}", json={"meeting_date": _day(12)}).get_json()["meeting"]
    assert moved["meeting_time"] == "14:00"
    assert _order(admin_client, _day(12)) == [["meeting", other["id"]], ["meeting", m["id"]]]
    assert _order(admin_client) == []
    t = _task(admin_client, task_time="09:30")
    moved_task = admin_client.patch(f"/api/planner/tasks/{t['id']}", json={"task_date": _day(12)}).get_json()["task"]
    assert moved_task["task_time"] == "09:30"
    assert _order(admin_client, _day(12))[-1] == ["task", t["id"]]


def test_a_next_plan_with_a_date_creates_the_follow_up_at_the_end_of_that_day(admin_client):
    existing = _meeting(admin_client, client_name="Same day", meeting_date=_day(9))
    first = _meeting(admin_client, meeting_date=_day(2), next_plan="Send the revised quote", next_date=_day(9))
    follow = [m for m in _day_view(admin_client, _day(9))["meetings"] if m["follow_up_of_id"] == first["id"]]
    assert len(follow) == 1
    f = follow[0]
    assert (f["client_name"], f["address"], f["purpose"], f["status"]) == ("Kalyani Warehousing", "Kamptee Road godown", "Send the revised quote", "planned")
    assert _order(admin_client, _day(9)) == [["meeting", existing["id"]], ["meeting", f["id"]]]
    moved = admin_client.patch(f"/api/planner/meetings/{first['id']}", json={"next_date": _day(11)}).get_json()["meeting"]
    assert moved["next_date"] == _day(11)
    again = [m for m in _day_view(admin_client, _day(11))["meetings"] if m["follow_up_of_id"] == first["id"]]
    assert len(again) == 1 and again[0]["id"] == f["id"]                                              # the same meeting, moved to its new day
    assert _order(admin_client, _day(9)) == [["meeting", existing["id"]]]


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


def test_upcoming_lists_what_is_ahead_in_tile_order_and_what_still_needs_a_remark(app, admin_client):
    second = _meeting(admin_client, client_name="Second tile", meeting_date=_day(4))
    first = _meeting(admin_client, client_name="First tile", meeting_date=_day(4))
    admin_client.post("/api/planner/order", json={"date": _day(4), "items": [["meeting", first["id"]], ["meeting", second["id"]]]})
    cancelled = _meeting(admin_client, client_name="Cancelled", meeting_date=_day(5))
    admin_client.patch(f"/api/planner/meetings/{cancelled['id']}", json={"status": "cancelled"})
    past = _meeting(admin_client, client_name="Past", meeting_date=_day(-3))                           # logging a meeting that already happened is allowed
    r = admin_client.get("/api/planner/upcoming").get_json()
    assert [m["id"] for m in r["meetings"]] == [first["id"], second["id"]]
    assert [m["id"] for m in r["needs_remark"]] == [past["id"]]
    admin_client.patch(f"/api/planner/meetings/{past['id']}", json={"status": "done", "remark": "Done"})
    assert admin_client.get("/api/planner/upcoming").get_json()["needs_remark"] == []


def test_tasks_can_be_ticked_and_removed(admin_client):
    t = _task(admin_client)
    done = admin_client.patch(f"/api/planner/tasks/{t['id']}", json={"done": True}).get_json()["task"]
    assert done["done"] is True
    assert admin_client.patch(f"/api/planner/tasks/{t['id']}", json={"done": "yes"}).status_code == 422
    assert admin_client.post("/api/planner/tasks", json={"task_date": _day()}).status_code == 422
    assert admin_client.delete(f"/api/planner/tasks/{t['id']}").status_code == 204
    assert admin_client.delete(f"/api/planner/tasks/{t['id']}").status_code == 404
    assert _day_view(admin_client)["tasks"] == []


def test_the_contact_and_address_are_stored_encrypted(app, admin_client):
    m = _meeting(admin_client)
    with app.app_context():
        raw = db.session.execute(db.text("select address, contact_no from planner_meetings where id = :i"), {"i": m["id"]}).one()
        assert "9800000001" not in raw[1] and "Kamptee" not in raw[0]
        assert db.session.get(PlannerMeeting, m["id"]).contact_no == "9800000001"


def _hold(c, meeting, **over):
    return c.patch(f"/api/planner/meetings/{meeting['id']}", json={"status": "done", **over}).get_json()["meeting"]


def test_held_meetings_are_listed_newest_first_with_their_remark_and_next_plan(admin_client):
    old = _meeting(admin_client, client_name="Old one", meeting_date=_day(-20))
    new = _meeting(admin_client, client_name="New one", meeting_date=_day(-2))
    _hold(admin_client, old, remark="Wants a discount")
    _hold(admin_client, new, remark="Agreed", next_plan="Send the contract")
    _meeting(admin_client, client_name="Still planned", meeting_date=_day(-1))
    cancelled = _meeting(admin_client, client_name="Cancelled", meeting_date=_day(-3))
    admin_client.patch(f"/api/planner/meetings/{cancelled['id']}", json={"status": "cancelled"})
    r = admin_client.get("/api/planner/history").get_json()
    assert [m["client_name"] for m in r["meetings"]] == ["New one", "Old one"] and r["more"] is False
    assert (r["meetings"][0]["remark"], r["meetings"][0]["next_plan"]) == ("Agreed", "Send the contract")
    _hold(admin_client, new, status="planned")                                   # unticked again: it leaves the list
    assert [m["client_name"] for m in admin_client.get("/api/planner/history").get_json()["meetings"]] == ["Old one"]


def test_held_meetings_can_be_narrowed_by_date_and_by_client_or_purpose(admin_client):
    a = _meeting(admin_client, client_name="Sahyadri Cold Storage", purpose="Hydrant review", meeting_date=_day(-10))
    b = _meeting(admin_client, client_name="Orange City Hospital", purpose="Alarm AMC", meeting_date=_day(-5))
    c = _meeting(admin_client, client_name="100% Textiles_Co", purpose="Handover", meeting_date=_day(-1))
    for m in (a, b, c):
        _hold(admin_client, m)

    def names(**q):
        r = admin_client.get("/api/planner/history", query_string=q)
        assert r.status_code == 200
        return [m["client_name"] for m in r.get_json()["meetings"]]

    assert names(**{"from": _day(-6)}) == ["100% Textiles_Co", "Orange City Hospital"]
    assert names(to=_day(-6)) == ["Sahyadri Cold Storage"]
    assert names(**{"from": _day(-6), "to": _day(-2)}) == ["Orange City Hospital"]
    assert names(q="hospital") == ["Orange City Hospital"]                                 # any case
    assert names(q="alarm") == ["Orange City Hospital"]                                    # the purpose too
    assert names(q="100%") == ["100% Textiles_Co"] and names(q="%") == ["100% Textiles_Co"]  # a typed % is a character, not "anything"
    assert names(q="_") == ["100% Textiles_Co"]
    assert names(q="nobody") == []
    assert admin_client.get("/api/planner/history?from=soon").status_code == 422


def test_the_held_list_is_capped_and_says_when_there_are_more(admin_client, monkeypatch):
    from app import planner
    monkeypatch.setattr(planner, "HISTORY_LIMIT", 2)
    for i in range(3):
        _hold(admin_client, _meeting(admin_client, client_name=f"M{i}", meeting_date=_day(-i - 1)))
    r = admin_client.get("/api/planner/history").get_json()
    assert [m["client_name"] for m in r["meetings"]] == ["M0", "M1"] and r["more"] is True and r["limit"] == 2


def test_the_held_list_is_for_the_admin_only(client, admin_client):
    assert client.get("/api/planner/history").status_code == 403

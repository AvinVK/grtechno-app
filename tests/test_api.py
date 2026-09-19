from datetime import timedelta

from app.timeutil import today_local


def make(client, **fields):
    body = {"company": "Acme Plant", "contact_name": "R. Sharma", **fields}
    res = client.post("/api/leads", json=body)
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def test_create_requires_a_name(client):
    res = client.post("/api/leads", json={"phone": "123"})
    assert res.status_code == 422
    assert "company" in res.get_json()["fields"]


def test_create_rejects_bad_values(client):
    res = client.post("/api/leads", json={"company": "X", "est_value": "abc", "follow_up_date": "31-12-2026", "stage": "Nope"})
    fields = res.get_json()["fields"]
    assert set(fields) == {"est_value", "follow_up_date", "stage"}


def test_negative_and_nan_values_rejected(client):
    for bad in (-5, "NaN", "Infinity"):
        assert client.post("/api/leads", json={"company": "X", "est_value": bad}).status_code == 422


def test_api_requires_json(client):
    res = client.post("/api/leads", data={"company": "X"})
    assert res.status_code == 415


def test_new_lead_defaults_and_activity(client):
    lead = make(client, est_value="125000.50")
    assert lead["stage"] == "New enquiry"
    assert lead["est_value"] == 125000.5
    assert [a["kind"] for a in lead["activities"]] == ["created"]


def test_stage_change_logs_and_sets_closed_at(client):
    lead = make(client)
    res = client.patch(f"/api/leads/{lead['id']}", json={"stage": "Won"}).get_json()
    assert res["stage"] == "Won" and res["closed_at"]
    assert res["activities"][0]["text"] == "Stage changed: New enquiry \u2192 Won"

    reopened = client.patch(f"/api/leads/{lead['id']}", json={"stage": "Negotiation"}).get_json()
    assert reopened["closed_at"] is None


def test_same_stage_does_not_log(client):
    lead = make(client)
    res = client.patch(f"/api/leads/{lead['id']}", json={"stage": "New enquiry", "notes": "hi"}).get_json()
    assert len(res["activities"]) == 1


def test_follow_up_change_is_logged(client):
    lead = make(client)
    tomorrow = (today_local() + timedelta(days=1)).isoformat()
    res = client.patch(f"/api/leads/{lead['id']}", json={"follow_up_date": tomorrow}).get_json()
    assert res["follow_up_date"] == tomorrow
    assert res["activities"][0]["kind"] == "followup"
    cleared = client.patch(f"/api/leads/{lead['id']}", json={"follow_up_date": None}).get_json()
    assert cleared["activities"][0]["text"] == "Follow-up cleared"


def test_cannot_blank_both_names(client):
    lead = make(client)
    res = client.patch(f"/api/leads/{lead['id']}", json={"company": "", "contact_name": ""})
    assert res.status_code == 422


def test_notes_and_delete(client):
    lead = make(client)
    res = client.post(f"/api/leads/{lead['id']}/notes", json={"text": "Called, will revert Monday"})
    assert res.status_code == 201
    assert res.get_json()["activities"][0]["text"] == "Called, will revert Monday"
    assert client.post(f"/api/leads/{lead['id']}/notes", json={"text": "  "}).status_code == 422

    assert client.delete(f"/api/leads/{lead['id']}").status_code == 204
    assert client.get(f"/api/leads/{lead['id']}").status_code == 404
    assert client.get("/api/leads/999").get_json()["error"]


def test_summary_numbers(client):
    today = today_local()
    yesterday = (today - timedelta(days=1)).isoformat()
    make(client, est_value=100, follow_up_date=yesterday)                    # open, overdue
    make(client, est_value=200, follow_up_date=today.isoformat())            # open, due today
    make(client, est_value=300, follow_up_date=(today + timedelta(days=3)).isoformat())  # open, later
    won = make(client, est_value=1000)
    lost = make(client, est_value=50)
    client.patch(f"/api/leads/{won['id']}", json={"stage": "Won"})
    client.patch(f"/api/leads/{lost['id']}", json={"stage": "Lost"})

    s = client.get("/api/state").get_json()["summary"]
    assert s["open_count"] == 3
    assert s["open_value"] == 600
    assert s["due_count"] == 2 and s["overdue_count"] == 1
    assert s["won_month_count"] == 1 and s["won_month_value"] == 1000
    assert s["win_rate"] == 50


def test_summary_empty(client):
    s = client.get("/api/state").get_json()["summary"]
    assert s["win_rate"] is None and s["open_value"] == 0


def test_csv_export_neutralises_formulas(client):
    make(client, company='=HYPERLINK("http://evil")', notes="line1\nline2")
    res = client.get("/export.csv")
    assert res.mimetype == "text/csv"
    text = res.get_data(as_text=True)
    assert text.startswith("\ufeffID,Company")
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text


def test_settings_roundtrip(client):
    page = client.get("/settings")
    assert page.status_code == 200
    with client.session_transaction() as s:
        s["csrf"] = "tok"
    res = client.post("/settings", data={"csrf": "tok", "currency": "$", "country_code": "+1", "services": "A\nB\nA", "sources": "X"})
    assert res.status_code == 302
    st = client.get("/api/state").get_json()["settings"]
    assert st["currency"] == "$" and st["country_code"] == "1" and st["services"] == ["A", "B"]


def test_settings_needs_csrf(client):
    assert client.post("/settings", data={"currency": "$"}).status_code == 400

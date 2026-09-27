"""The reworked lead pipeline: multiple services per lead, an existing-client enquiry becoming a second
project (not a second client), the site-survey -> quote -> negotiation stage gates, survey photos, and
negotiation rounds. Uses admin_client throughout since these flows touch /api/clients and /api/projects,
which the plain sales_field "client" fixture cannot open (see test_projects.py's role tests)."""

import io

from app.extensions import db
from app.models import Client, Project, Service, Worker


def make_service(name, sort_order=1):
    s = Service(name=name, sort_order=sort_order)
    db.session.add(s)
    db.session.commit()
    return s


def make_staff(name="Ramesh Surveyor"):
    w = Worker(name=name, category="staff")
    db.session.add(w)
    db.session.commit()
    return w


def make_lead(admin_client, **fields):
    body = {"company": "Kalyani Cold Storage", "contact_name": "R. Kulkarni", "phone": "9800000001",
            "site_category": "Commercial complex", "site_pincode": "411001", "site_state": "Maharashtra",
            "site_district": "Pune", "site_city": "Pune City", "site_address": "Plot 12, MIDC", **fields}
    res = admin_client.post("/api/leads", json=body)
    assert res.status_code == 201, res.get_json()
    return res.get_json()


# ---------- multiple services ----------

def test_a_lead_can_have_more_than_one_service(admin_client):
    amc = make_service("AMC", 1)
    noc = make_service("Final NOC", 2)
    lead = make_lead(admin_client, service_ids=[amc.id, noc.id])
    assert set(lead["services"]) == {"AMC", "Final NOC"}


def test_service_ids_must_be_real_services(admin_client):
    res = admin_client.post("/api/leads", json={"company": "X", "service_ids": [9999]})
    assert res.status_code == 422 and "service_ids" in res.get_json()["fields"]


# ---------- who took the enquiry ----------

def test_enquired_by_must_be_staff_and_defaults_the_surveyor(admin_client):
    staff = make_staff("Priya Frontdesk")
    manpower = Worker(name="Not staff", category="manpower")
    db.session.add(manpower)
    db.session.commit()

    bad = admin_client.post("/api/leads", json={"company": "X", "enquired_by_id": manpower.id})
    assert bad.status_code == 422 and "enquired_by_id" in bad.get_json()["fields"]

    lead = make_lead(admin_client, enquired_by_id=staff.id)
    assert lead["enquired_by_id"] == staff.id and lead["enquired_by_name"] == "Priya Frontdesk"

    # The survey doesn't inherit a surveyor server-side (that's a client-side default only) - it starts empty.
    detail = admin_client.get(f"/api/leads/{lead['id']}").get_json()
    assert detail["survey"] is None


# ---------- an enquiry for an existing client ----------

def test_existing_client_lead_needs_no_company_name(admin_client):
    won = admin_client.post("/api/projects", json={"new_client_name": "Orchid Heights CHS"}).get_json()
    cid = won["project"]["client_id"]
    res = admin_client.post("/api/leads", json={"client_id": cid})
    assert res.status_code == 201, res.get_json()
    assert res.get_json()["client_id"] == cid


def test_existing_client_lead_must_be_a_client_you_can_see(admin_client, client):
    won = admin_client.post("/api/projects", json={"new_client_name": "Only Mine Ltd"}).get_json()
    cid = won["project"]["client_id"]
    # "client" here is the plain sales_field fixture, which has leads but not clients/projects access -
    # it can still raise a lead, just not for a client it can't see.
    res = client.post("/api/leads", json={"client_id": cid})
    assert res.status_code == 422 and "client_id" in res.get_json()["fields"]


def test_winning_an_existing_client_lead_adds_a_second_project_not_a_second_client(admin_client):
    first = admin_client.post("/api/projects", json={"new_client_name": "Orchid Heights CHS"}).get_json()["project"]
    lead = admin_client.post("/api/leads", json={"client_id": first["client_id"]}).get_json()
    assert admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Won"}).status_code == 200

    detail = admin_client.get(f"/api/leads/{lead['id']}").get_json()
    second_project = db.session.get(Project, detail["project_id"])
    assert second_project.client_id == first["client_id"]
    assert Client.query.count() == 1 and Project.query.count() == 2


# ---------- stage gates ----------

def test_quote_sent_requires_a_completed_survey(admin_client):
    lead = make_lead(admin_client)
    res = admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Site survey"})
    assert res.status_code == 200
    blocked = admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Quote sent"})
    assert blocked.status_code == 422 and "survey" in blocked.get_json()["error"]

    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20"})
    ok = admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Quote sent"})
    assert ok.status_code == 200


def test_negotiation_requires_a_sent_quote(admin_client):
    lead = make_lead(admin_client)
    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Site survey"})
    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20"})
    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Quote sent"})

    blocked = admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Negotiation"})
    assert blocked.status_code == 422 and "quote" in blocked.get_json()["error"]

    admin_client.patch(f"/api/leads/{lead['id']}", json={"quote_sent_date": "2026-09-22", "est_value": 500000})
    ok = admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Negotiation"})
    assert ok.status_code == 200


# ---------- site survey ----------

def test_survey_upsert_and_surveyor_must_be_staff(admin_client):
    lead = make_lead(admin_client)
    staff = make_staff()
    manpower = Worker(name="Not staff", category="manpower")
    db.session.add(manpower)
    db.session.commit()

    bad = admin_client.put(f"/api/leads/{lead['id']}/survey", json={"surveyor_id": manpower.id})
    assert bad.status_code == 422 and "surveyor_id" in bad.get_json()["fields"]

    ok = admin_client.put(f"/api/leads/{lead['id']}/survey", json={
        "survey_date": "2026-09-20", "surveyor_id": staff.id,
        "rep_name": "Site Manager", "rep_role": "Manager", "rep_phone": "9900000000",
    })
    assert ok.status_code == 200
    survey = ok.get_json()["survey"]
    assert survey["survey_date"] == "2026-09-20" and survey["surveyor_name"] == "Ramesh Surveyor"
    assert survey["rep_name"] == "Site Manager" and survey["rep_phone"] == "9900000000"

    # upsert again - same row, not a second one
    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-21"})
    assert admin_client.get(f"/api/leads/{lead['id']}").get_json()["survey"]["survey_date"] == "2026-09-21"


def test_saving_a_completed_survey_advances_a_new_enquiry_to_site_survey(admin_client):
    lead = make_lead(admin_client)
    assert lead["stage"] == "New enquiry"

    # No date yet - just rep details - doesn't count as "completed", so the stage stays put.
    partial = admin_client.put(f"/api/leads/{lead['id']}/survey", json={"rep_name": "Site Manager"})
    assert partial.get_json()["stage"] == "New enquiry"

    advanced = admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20"})
    assert advanced.get_json()["stage"] == "Site survey"
    assert any("Site survey" in a["text"] for a in advanced.get_json()["activities"])


def test_editing_a_survey_later_does_not_move_the_stage_backwards(admin_client):
    lead = make_lead(admin_client)
    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20"})
    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Quote sent", "quote_sent_date": "2026-09-22"})

    edited = admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-21", "rep_name": "New rep"})
    assert edited.get_json()["stage"] == "Quote sent"


def test_sending_a_quote_advances_site_survey_to_quote_sent(admin_client):
    lead = make_lead(admin_client)
    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20"})
    assert admin_client.get(f"/api/leads/{lead['id']}").get_json()["stage"] == "Site survey"

    sent = admin_client.patch(f"/api/leads/{lead['id']}", json={"quote_sent_date": "2026-09-22", "est_value": 56000})
    assert sent.get_json()["stage"] == "Quote sent"        # not skipped straight to Negotiation
    assert any("Quote sent" in a["text"] for a in sent.get_json()["activities"])

    # editing the quote again afterwards doesn't move it a second time
    edited = admin_client.patch(f"/api/leads/{lead['id']}", json={"quote_sent_date": "2026-09-23", "est_value": 60000})
    assert edited.get_json()["stage"] == "Quote sent"


def test_adding_a_negotiation_round_advances_quote_sent_to_negotiation(admin_client):
    lead = make_lead(admin_client)
    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20"})
    admin_client.patch(f"/api/leads/{lead['id']}", json={"quote_sent_date": "2026-09-22", "est_value": 56000})
    assert admin_client.get(f"/api/leads/{lead['id']}").get_json()["stage"] == "Quote sent"

    first = admin_client.post(f"/api/leads/{lead['id']}/negotiations", json={
        "date": "2026-09-24", "authorized_person": "Mr. Rao", "estimate": 54000, "finalized": False,
    })
    assert first.status_code == 201
    assert first.get_json()["stage"] == "Negotiation"        # completing Quote sent's own step, one stage forward
    assert any("Negotiation" in a["text"] for a in first.get_json()["activities"])

    # a second round afterwards doesn't move it a second time
    second = admin_client.post(f"/api/leads/{lead['id']}/negotiations", json={
        "date": "2026-09-26", "authorized_person": "Mr. Rao", "estimate": 50000, "finalized": False,
    })
    assert second.get_json()["stage"] == "Negotiation"


def test_survey_photos_upload_and_delete(admin_client):
    lead = make_lead(admin_client)
    no_survey = admin_client.post(f"/api/leads/{lead['id']}/survey/photos", data={}, content_type="multipart/form-data")
    assert no_survey.status_code == 422

    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20"})
    photo = (io.BytesIO(b"\xff\xd8\xff\xe0fakejpeg"), "site.jpg")
    up = admin_client.post(f"/api/leads/{lead['id']}/survey/photos", data={"photos": [photo]},
                            content_type="multipart/form-data")
    assert up.status_code == 201
    photos = up.get_json()["survey"]["photos"]
    assert len(photos) == 1 and photos[0]["url"].startswith("/uploads/survey/")

    photo_id = photos[0]["id"]
    deleted = admin_client.delete(f"/api/leads/{lead['id']}/survey/photos/{photo_id}")
    assert deleted.status_code == 200 and deleted.get_json()["survey"]["photos"] == []


def test_non_image_upload_is_rejected(admin_client):
    lead = make_lead(admin_client)
    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20"})
    bad_file = (io.BytesIO(b"not an image"), "notes.txt")
    res = admin_client.post(f"/api/leads/{lead['id']}/survey/photos", data={"photos": [bad_file]},
                             content_type="multipart/form-data")
    assert res.status_code == 422


# ---------- negotiation rounds ----------

def _quoted_lead(admin_client):
    lead = make_lead(admin_client)
    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Site survey"})
    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20"})
    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Quote sent", "quote_sent_date": "2026-09-21", "est_value": 500000})
    return lead


def test_negotiation_rounds_added_edited_and_used_as_the_project_estimate(admin_client):
    lead = _quoted_lead(admin_client)
    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Negotiation"})

    first = admin_client.post(f"/api/leads/{lead['id']}/negotiations", json={
        "date": "2026-09-22", "authorized_person": "Mr. Rao", "estimate": 480000, "finalized": False,
    })
    assert first.status_code == 201
    rounds = first.get_json()["negotiations"]
    assert len(rounds) == 1 and rounds[0]["round_no"] == 1 and rounds[0]["finalized"] is False

    second = admin_client.post(f"/api/leads/{lead['id']}/negotiations", json={
        "date": "2026-09-24", "authorized_person": "Mr. Rao", "estimate": 460000, "finalized": True,
    })
    round_id = second.get_json()["negotiations"][1]["id"]
    edited = admin_client.patch(f"/api/leads/{lead['id']}/negotiations/{round_id}", json={
        "date": "2026-09-24", "authorized_person": "Mr. Rao", "estimate": 455000, "finalized": True,
    })
    assert edited.get_json()["negotiations"][1]["estimate"] == 455000

    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Won"})
    project_id = admin_client.get(f"/api/leads/{lead['id']}").get_json()["project_id"]
    assert float(db.session.get(Project, project_id).estimated_amount) == 455000        # latest round wins, not est_value


def test_negotiation_needs_a_quote_first(admin_client):
    lead = make_lead(admin_client)
    res = admin_client.post(f"/api/leads/{lead['id']}/negotiations", json={"estimate": 100})
    assert res.status_code == 422


# ---------- client total across projects ----------

def test_client_total_estimated_value_across_projects(admin_client):
    first = admin_client.post("/api/projects", json={"new_client_name": "Orchid Heights CHS", "status": "running"}).get_json()["project"]
    admin_patch = admin_client.patch(f"/api/projects/{first['id']}", json={"title": first["title"], "estimated_amount": "200000"})
    assert admin_patch.status_code == 200, admin_patch.get_json()

    lead = admin_client.post("/api/leads", json={"client_id": first["client_id"]}).get_json()
    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Site survey"})
    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20"})
    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Quote sent", "quote_sent_date": "2026-09-21", "est_value": 300000})
    admin_client.patch(f"/api/leads/{lead['id']}", json={"stage": "Won"})

    detail = admin_client.get(f"/api/clients/{first['client_id']}").get_json()
    assert detail["client"]["total_estimated_value"] == 500000
    assert {p["estimated_amount"] for p in detail["projects"]} == {200000, 300000}

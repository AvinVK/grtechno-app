from app.extensions import db
from app.models import SiteCategory, SiteCategoryRequest


def _survey_with(admin_client, category):
    lead = admin_client.post("/api/leads", json={"company": "Kiln Co", "service": "AMC", "source": "Referral",
                                                 "phone": "9800000011", "follow_up_date": "2026-09-30"}).get_json()
    admin_client.put(f"/api/leads/{lead['id']}/survey", json={"survey_date": "2026-09-20", "site_category": category})
    return lead["id"]


def test_typed_category_waits_for_approval_before_it_is_on_the_list(admin_client):
    assert "Brick factory" not in SiteCategory.active_names()
    _survey_with(admin_client, "Brick factory")
    waiting = admin_client.get("/api/site-categories/requests").get_json()
    assert [r["name"] for r in waiting["requests"]] == ["Brick factory"]
    assert "Brick factory" not in admin_client.get("/api/state").get_json()["settings"]["site_categories"]

    req_id = waiting["requests"][0]["id"]
    assert admin_client.post(f"/api/site-categories/requests/{req_id}/approve").status_code == 200
    assert "Brick factory" in admin_client.get("/api/state").get_json()["settings"]["site_categories"]
    assert admin_client.get("/api/site-categories/requests").get_json()["requests"] == []


def test_admin_can_point_a_typed_category_at_an_existing_one(admin_client):
    lead_id = _survey_with(admin_client, "Factory shed")
    req_id = admin_client.get("/api/site-categories/requests").get_json()["requests"][0]["id"]
    assert admin_client.post(f"/api/site-categories/requests/{req_id}/redirect", json={"target": "Plant"}).status_code == 200
    assert admin_client.get(f"/api/leads/{lead_id}").get_json()["survey"]["site_category"] == "Plant"
    assert "Factory shed" not in SiteCategory.active_names()
    assert db.session.get(SiteCategoryRequest, req_id).status == "redirected"
    assert admin_client.post(f"/api/site-categories/requests/{req_id}/redirect", json={"target": "Plant"}).status_code == 409


def test_only_the_admin_sees_and_decides_requests(admin_client, client):
    _survey_with(admin_client, "Godown")
    assert client.get("/api/site-categories/requests").status_code == 403
    req_id = admin_client.get("/api/site-categories/requests").get_json()["requests"][0]["id"]
    assert client.post(f"/api/site-categories/requests/{req_id}/approve").status_code == 403
    assert admin_client.post(f"/api/site-categories/requests/{req_id}/redirect", json={"target": "Nope"}).status_code == 422

"""Warn before a duplicate material is created (kohal, 2026-11-14: "Nipple 25mm and 25mm nipple is same ... even spelling diff a little bit or spacing
should be taken care") - see app/material_match.py."""

import pytest

from app.extensions import db
from app.material_match import THRESHOLD, similarity
from app.models import Material


@pytest.mark.parametrize("a, b", [
    ("Nipple 25mm", "25mm Nipple"),                     # word order
    ("Nipple25mm", "25mm Nipple"),                      # no spaces
    ("Nipple 25 MM", "25mm Nipple"),                    # case and a space inside the size
    ("Nipple 50mm", "50 MM Nipple"),
    ("Gate valve 2 inch", 'Gatevalve 2"'),              # spacing, and inch written as a mark
    ("Nipple 25mm x6 inch", 'Nipple 25mm x6"'),
    ("Niple 25mm", "25mm Nipple"),                      # a missing letter
    ("Hose nipple", "Hose nippel"),                     # two letters swapped
    ("Cement", "Cemnt"),
    ("MS pipe 2 inches", "ms pipe 2 inch"),
    ("Hose  Nipple", "hose-nipple"),                    # extra spaces and a dash
    ("25mm", "25 mm"),
])
def test_names_that_are_the_same_thing_are_flagged(a, b):
    assert similarity(a, b) >= THRESHOLD, (a, b, similarity(a, b))
    assert similarity(b, a) == similarity(a, b)


@pytest.mark.parametrize("a, b", [
    ("Nipple 25mm", "Nipple 50mm"),                     # a different size is a different item, however alike the words
    ("Pipe 2 inch", "Pipe 3 inch"),
    ("Nipple 25mm", 'Nipple 25mm x6"'),                 # an extra number: could be a different length, the names cannot say
    ("Elbow 25mm", "Tee 25mm"),
    ("Cement", "Hose nipple"),
])
def test_different_things_are_not_flagged(a, b):
    assert similarity(a, b) < THRESHOLD, (a, b, similarity(a, b))


def test_a_name_with_no_words_is_never_compared():
    assert similarity("25", "25") == 0.0 and similarity("", "Nipple") == 0.0


def _stock(*names, active=True):
    for n in names:
        db.session.add(Material(name=n, unit="PCS", is_active=active))
    db.session.commit()


def test_the_endpoint_lists_lookalikes_most_alike_first_with_what_is_in_stock(app, admin_client):
    with app.app_context():
        _stock("25mm Nipple", "Nipple 25 mm", "Nipple 50mm", "Hose nipple")
        m = Material.query.filter_by(name="25mm Nipple").one()
        m.stock_qty = 4
        db.session.commit()
    res = admin_client.get("/api/materials/similar", query_string={"name": "Nipple 25mm"})
    matches = res.get_json()["matches"]
    assert res.status_code == 200 and {x["name"] for x in matches} == {"25mm Nipple", "Nipple 25 mm"}
    first = next(x for x in matches if x["name"] == "25mm Nipple")
    assert (first["unit"], first["stock_qty"], first["score"]) == ("PCS", 4.0, 1.0) and first["code"].startswith("MAT-")
    assert [x["score"] for x in matches] == sorted((x["score"] for x in matches), reverse=True)


def test_it_leaves_out_the_material_being_edited_inactive_ones_and_too_short_names(app, admin_client):
    with app.app_context():
        _stock("25mm Nipple")
        _stock("Nipple 25 mm", active=False)
        mid = Material.query.filter_by(name="25mm Nipple").one().id
    assert admin_client.get("/api/materials/similar", query_string={"name": "Nipple 25mm", "exclude_id": mid}).get_json()["matches"] == []
    assert [x["name"] for x in admin_client.get("/api/materials/similar", query_string={"name": "Nipple 25mm"}).get_json()["matches"]] == ["25mm Nipple"]
    for short in ("", "ab", "  "):
        assert admin_client.get("/api/materials/similar", query_string={"name": short}).get_json()["matches"] == []


def test_it_gives_at_most_three_and_needs_a_sign_in(app, admin_client, anon):
    with app.app_context():
        _stock("Nipple 25mm", "25mm nipple", "25 mm Nipple", "Nipple 25 MM", "Nipple-25mm")
    assert len(admin_client.get("/api/materials/similar", query_string={"name": "Nipple 25mm"}).get_json()["matches"]) == 3
    assert anon.get("/api/materials/similar", query_string={"name": "Nipple 25mm"}).status_code in (302, 401, 403)

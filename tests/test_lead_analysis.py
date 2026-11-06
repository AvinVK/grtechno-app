"""Lead analysis (kohal, 2026-11-05) - leads per month, per source, time on each stage, and who brought them in."""

from datetime import timedelta

from app.extensions import db
from app.models import Activity, Lead, Worker, utcnow


def _lead(owner=None, enquired_by=None, **kw):
    lead = Lead(contact_name=kw.pop("contact", "Contact"), company=kw.pop("company", "Acme"), phone="9999900000",
                owner_code=owner.code if owner else None, enquired_by=enquired_by, **kw)
    db.session.add(lead)
    db.session.flush()
    return lead


def _move(lead, text, at):
    db.session.add(Activity(lead=lead, kind="stage", text=text, created_at=at))


def _seed(app):
    """Three leads in the last few weeks and one from 14 months ago.
    A: Website, Ravi - New enquiry for 2 days, Site survey for 3, then Quote sent (still there, since day 5), created 10 days ago.
    B: Referral, Ravi - lost, created 40 days ago, spent 4 days at New enquiry.
    C: Website, entered by the owner (no enquired-by) - still a new enquiry, created 3 days ago.
    D: Referral, Ravi - created 14 months ago (outside the monthly chart), still New enquiry."""
    with app.app_context():
        now = utcnow()
        ravi = Worker(name="Ravi Sales", category="staff")
        db.session.add(ravi)
        db.session.flush()
        a = _lead(enquired_by=ravi, source="Website", stage="Quote sent", created_at=now - timedelta(days=10))
        _move(a, "Stage changed: New enquiry → Site survey", now - timedelta(days=8))
        _move(a, "Stage changed: Site survey → Quote sent", now - timedelta(days=5))
        b = _lead(enquired_by=ravi, source="Referral", stage="Lost", created_at=now - timedelta(days=40))
        _move(b, "Stage changed: New enquiry → Lost", now - timedelta(days=36))
        _lead(source="Website", stage="New enquiry", created_at=now - timedelta(days=3))
        _lead(enquired_by=ravi, source="Referral", stage="New enquiry", created_at=now - timedelta(days=430))
        db.session.commit()


def _this_month():
    from app.timeutil import today_local
    t = today_local()
    return f"{t.year}-{t.month:02d}"


def _received_ages_in_range(first_day):
    """How many of the seeded leads (created 10, 40 and 3 days ago, plus one 430 days ago) came in on or after `first_day`."""
    from datetime import timedelta as td
    from app.timeutil import today_local
    return sum(1 for age in (10, 40, 3, 430) if today_local() - td(days=age) >= first_day)


def test_leads_over_time_defaults_to_the_last_twelve_months(app, admin_client):
    _seed(app)
    data = admin_client.get("/api/lead-analysis").get_json()
    trend = data["trend"]
    assert trend["range"] == "12" and trend["unit"] == "month" and len(trend["points"]) == 12 and trend["points"][-1]["key"] == _this_month()
    assert trend["total"] == 3                                                  # the 14-month-old lead is outside the window
    assert data["total"] == 4                                                   # ...but counts in "all time" for the other charts
    assert [t["value"] for t in data["trends"]] == ["30d", "1", "3", "6", "12"]


def test_leads_over_time_has_ranges_of_its_own(app, admin_client):
    from datetime import timedelta as td, date
    from app.timeutil import today_local
    _seed(app)
    today = today_local()
    days30 = admin_client.get("/api/lead-analysis?trend=30d").get_json()["trend"]
    assert days30["unit"] == "day" and len(days30["points"]) == 30 and days30["points"][-1]["key"] == today.isoformat()
    assert days30["points"][0]["key"] == (today - td(days=29)).isoformat() and days30["total"] == 2        # the 10-day-old and the 3-day-old

    this_month = admin_client.get("/api/lead-analysis?trend=1").get_json()["trend"]
    assert this_month["unit"] == "day" and len(this_month["points"]) == today.day and this_month["points"][0]["key"] == today.replace(day=1).isoformat()
    assert this_month["total"] == _received_ages_in_range(today.replace(day=1))

    for key, months in (("3", 3), ("6", 6)):
        t = admin_client.get(f"/api/lead-analysis?trend={key}").get_json()["trend"]
        y, m = today.year, today.month - (months - 1)
        while m <= 0:
            y, m = y - 1, m + 12
        assert t["unit"] == "month" and len(t["points"]) == months
        assert t["total"] == _received_ages_in_range(date(y, m, 1))
    assert admin_client.get("/api/lead-analysis?trend=forever").status_code == 422


def test_the_over_time_range_does_not_change_the_other_charts(app, admin_client):
    _seed(app)
    a = admin_client.get("/api/lead-analysis?trend=30d").get_json()
    b = admin_client.get("/api/lead-analysis?trend=12").get_json()
    assert (a["total"], a["sources"], a["brought_by"]) == (b["total"], b["sources"], b["brought_by"])


def test_leads_per_source_are_counted_and_the_period_cuts_by_when_they_came_in(app, admin_client):
    _seed(app)
    sources = {s["source"]: s["count"] for s in admin_client.get("/api/lead-analysis").get_json()["sources"]}
    assert sources == {"Website": 2, "Referral": 2}
    last_3 = admin_client.get("/api/lead-analysis?period=3").get_json()
    assert last_3["total"] == 3 and {s["source"]: s["count"] for s in last_3["sources"]} == {"Website": 2, "Referral": 1}
    assert admin_client.get("/api/lead-analysis?period=forever").status_code == 422


def test_time_on_each_stage_comes_from_the_recorded_stage_changes(app, admin_client):
    _seed(app)
    stages = {s["stage"]: s for s in admin_client.get("/api/lead-analysis?period=12").get_json()["stage_times"]}
    # New enquiry: A stayed 2 days, B stayed 4 -> average 3.0, typical (median) 3.0; C is there now, and D (14 months old) is not in this period
    assert stages["New enquiry"]["avg_days"] == 3.0 and stages["New enquiry"]["stays"] == 2
    assert stages["New enquiry"]["now"] == 1 and 2.9 <= stages["New enquiry"]["now_avg_days"] <= 3.1
    assert stages["Site survey"]["avg_days"] == 3.0 and stages["Site survey"]["stays"] == 1 and stages["Site survey"]["now"] == 0
    assert stages["Quote sent"]["avg_days"] is None and stages["Quote sent"]["now"] == 1                     # A is still there, nobody has left
    assert 4.9 <= stages["Quote sent"]["now_avg_days"] <= 5.1
    assert [s["stage"] for s in admin_client.get("/api/lead-analysis").get_json()["stage_times"]][:2] == ["New enquiry", "Site survey"]


def test_brought_by_counts_each_persons_leads_and_how_they_turned_out(app, admin_client):
    _seed(app)
    people = {p["name"]: p for p in admin_client.get("/api/lead-analysis").get_json()["brought_by"]}
    ravi = people["Ravi Sales"]
    assert (ravi["total"], ravi["won"], ravi["lost"], ravi["open"]) == (3, 0, 1, 2)
    assert people["Not set"]["total"] == 1                                    # entered by nobody recorded: no one to credit
    assert list(people)[0] == "Ravi Sales"                                    # most leads first


def test_a_salesperson_only_sees_the_analysis_of_their_own_leads(app, admin_client, client, user):
    _seed(app)
    with app.app_context():
        _lead(owner=db.session.get(type(user), user.code), source="Walk-in", stage="New enquiry", created_at=utcnow() - timedelta(days=1))
        db.session.commit()
    mine = client.get("/api/lead-analysis").get_json()
    assert mine["total"] == 1 and mine["scope"] == "your leads" and [s["source"] for s in mine["sources"]] == ["Walk-in"]
    assert admin_client.get("/api/lead-analysis").get_json()["scope"] == "everyone's leads"


def test_the_page_needs_the_leads_service_and_has_a_tile_on_me(admin_client, client, accounts_client):
    assert admin_client.get("/lead-analysis").status_code == 200 and client.get("/lead-analysis").status_code == 200
    assert accounts_client.get("/lead-analysis").status_code == 403           # the Accountant has no Leads service
    assert accounts_client.get("/api/lead-analysis").status_code == 403
    assert 'href="/lead-analysis"' in admin_client.get("/me").data.decode()
    assert 'href="/lead-analysis"' not in accounts_client.get("/me").data.decode()


def test_the_last_thirty_days_is_a_period_for_the_other_charts(app, admin_client):
    _seed(app)
    data = admin_client.get("/api/lead-analysis?period=30d").get_json()
    assert data["total"] == 2                                                   # the 10-day-old and the 3-day-old; not the 40- or 430-day-old
    assert {s["source"]: s["count"] for s in data["sources"]} == {"Website": 2}
    assert [p["value"] for p in data["periods"]] == ["all", "12", "6", "3", "30d"]


def test_each_persons_success_rate_is_won_out_of_the_leads_decided(app, admin_client):
    _seed(app)
    with app.app_context():
        ravi = Worker.query.filter_by(name="Ravi Sales").one()
        _lead(enquired_by=ravi, source="Website", stage="Won", created_at=utcnow() - timedelta(days=5))
        _lead(enquired_by=ravi, source="Website", stage="Won", created_at=utcnow() - timedelta(days=4))
        db.session.commit()
    people = {p["name"]: p for p in admin_client.get("/api/lead-analysis").get_json()["brought_by"]}
    # Ravi: 2 won, 1 lost (the 40-day-old), 2 still open -> 2 of the 3 decided
    assert (people["Ravi Sales"]["won"], people["Ravi Sales"]["lost"], people["Ravi Sales"]["success_rate"]) == (2, 1, 67)
    assert people["Not set"]["success_rate"] is None                              # nothing decided yet, so no rate rather than 0%

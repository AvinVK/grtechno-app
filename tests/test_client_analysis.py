"""Client analysis (kohal, 2026-11-05) - the Tally subtab (for each client, what their projects are worth, what has been paid and what
is left) and the Analysis subtab (charts over the same figures)."""

from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import Client, Project, ProjectPayment


def _seed(app):
    """Acme: Plant A worth 1,00,000 less a 10,000 discount (90,000), 30,000 paid and a further 20,000 step not yet paid; Plant B
    finished at a final amount of 50,000 with 50,000 paid. Beta: one project with no value set and 5,000 received. An adhoc
    customer, who is not a client."""
    with app.app_context():
        acme, beta = Client(name="Acme Industries", contact_name="Mr. Acme", city="Nagpur"), Client(name="Beta Works")
        adhoc = Client(name="Counter Customer", is_adhoc=True)
        db.session.add_all([acme, beta, adhoc])
        db.session.flush()
        a = Project(client=acme, title="Plant A", estimated_amount=Decimal("100000"), discount_amount=Decimal("10000"), status="running")
        b = Project(client=acme, title="Plant B", estimated_amount=Decimal("45000"), final_amount=Decimal("50000"), status="completed")
        c = Project(client=beta, title="Unpriced", status="planned")
        d = Project(client=adhoc, title="Counter sale", estimated_amount=Decimal("999"), status="billed")
        db.session.add_all([a, b, c, d])
        db.session.flush()
        db.session.add_all([
            ProjectPayment(project=a, label="Advance", amount=Decimal("30000"), paid_date=date(2026, 10, 1)),
            ProjectPayment(project=a, label="Next", amount=Decimal("20000")),                      # planned, not received
            ProjectPayment(project=b, label="All", amount=Decimal("50000"), paid_date=date(2026, 10, 5)),
            ProjectPayment(project=c, label="Advance", amount=Decimal("5000"), paid_date=date(2026, 10, 6)),
        ])
        db.session.commit()
        return acme.id, beta.id


def test_the_client_tally_shows_worth_paid_and_left_for_each_client(app, admin_client):
    acme_id, beta_id = _seed(app)
    data = admin_client.get("/api/clients/tally").get_json()
    rows = {r["name"]: r for r in data["clients"]}
    assert set(rows) == {"Acme Industries", "Beta Works"}                     # the adhoc customer is not a client
    acme = rows["Acme Industries"]
    assert (acme["projects"], acme["worth"], acme["paid"], acme["left"]) == (2, 140000.0, 80000.0, 60000.0)
    beta = rows["Beta Works"]
    assert (beta["worth"], beta["paid"], beta["left"]) == (0.0, 5000.0, -5000.0)  # money in against a project with no value yet
    assert data["totals"] == {"worth": 140000.0, "paid": 85000.0, "left": 55000.0}
    assert [r["name"] for r in data["clients"]] == ["Acme Industries", "Beta Works"]   # most left to receive first


def test_a_clients_tally_breaks_down_by_project(app, admin_client):
    acme_id, _ = _seed(app)
    data = admin_client.get(f"/api/clients/{acme_id}/tally").get_json()
    assert data["client"]["left"] == 60000.0 and data["can_open_projects"] is True
    projects = {p["title"]: p for p in data["projects"]}
    assert (projects["Plant A"]["worth"], projects["Plant A"]["paid"], projects["Plant A"]["left"]) == (90000.0, 30000.0, 60000.0)
    assert (projects["Plant B"]["worth"], projects["Plant B"]["paid"], projects["Plant B"]["left"]) == (50000.0, 50000.0, 0.0)
    assert projects["Plant B"]["status"] == "completed"
    # each project carries its payment steps for the slide-up (read only): the advance received, the next one still pending
    steps = {x["label"]: x for x in projects["Plant A"]["payments"]}
    assert steps["Advance"]["amount"] == 30000.0 and steps["Advance"]["paid_date"] == "2026-10-01"
    assert steps["Next"]["amount"] == 20000.0 and steps["Next"]["paid_date"] is None
    unpriced = admin_client.get(f"/api/clients/{_seed_beta(app)}/tally").get_json()["projects"][0]
    assert unpriced["worth"] is None and unpriced["left"] is None and unpriced["paid"] == 5000.0


def _seed_beta(app):
    with app.app_context():
        return Client.query.filter_by(name="Beta Works").one().id


def test_the_tally_needs_the_clients_service(app, admin_client, client):
    _seed(app)
    assert client.get("/api/clients/tally").status_code == 403                # sales has no Clients service
    assert client.get("/client-analysis").status_code == 403
    assert client.get("/api/clients/analysis").status_code == 403
    assert admin_client.get("/client-analysis").status_code == 200
    old = admin_client.get("/client-tally")                                    # the old address now lands on the Tally subtab
    assert old.status_code == 302 and old.headers["Location"].endswith("/client-analysis#tally")
    assert admin_client.get("/api/clients/999999/tally").status_code == 404


def test_the_me_tile_is_client_analysis_not_the_clients_tab_again(admin_client):
    html = admin_client.get("/me").data.decode()
    assert 'class="me-tile" href="/client-analysis"' in html and "Client analysis" in html and "Client tally" not in html
    assert 'class="me-tile" href="/clients"' not in html


def test_the_analysis_subtab_summarises_worth_status_and_money_received(app, admin_client):
    _seed(app)
    data = admin_client.get("/api/clients/analysis").get_json()
    assert data["clients"] == 2 and data["totals"] == {"worth": 140000.0, "paid": 85000.0, "left": 55000.0}
    assert [(r["name"], r["worth"], r["paid"]) for r in data["top_clients"]] == [("Acme Industries", 140000.0, 80000.0)]   # Beta has no value set
    status = {r["status"]: r for r in data["status"]}
    assert (status["running"]["projects"], status["running"]["worth"]) == (1, 90000.0) and status["completed"]["worth"] == 50000.0
    assert status["planned"]["projects"] == 1 and "billed" not in status                    # the adhoc customer's sale is not a client project
    received = data["received"]
    assert received["range"] == "12" and len(received["points"]) == 12 and received["total"] <= 85000.0
    assert [r["value"] for r in data["ranges"]] == ["3", "6", "12"]
    assert admin_client.get("/api/clients/analysis?range=forever").status_code == 422


def test_money_received_is_added_up_by_the_month_it_came_in(app, admin_client):
    from app.timeutil import months_back, today_local
    _seed(app)

    def total(span):
        return admin_client.get(f"/api/clients/analysis?range={span}").get_json()["received"]["total"]
    before = {span: total(span) for span in ("3", "6", "12")}
    with app.app_context():
        plant = Project.query.filter_by(title="Plant A").one()
        four_back = months_back(today_local(), 4)                              # inside the last 6 months, outside the last 3
        db.session.add(ProjectPayment(project=plant, label="Earlier", amount=Decimal("7000"), paid_date=four_back))
        db.session.add(ProjectPayment(project=plant, label="Long ago", amount=Decimal("9000"), paid_date=date(2020, 1, 1)))   # outside every range
        db.session.commit()
    assert total("3") == before["3"]
    assert total("6") == before["6"] + 7000.0 and total("12") == before["12"] + 7000.0
    points = admin_client.get("/api/clients/analysis?range=6").get_json()["received"]["points"]
    assert points[1]["count"] >= 7000.0 and points[1]["key"] == f"{four_back.year}-{four_back.month:02d}"

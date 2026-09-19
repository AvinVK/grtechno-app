from app.extensions import db
from app.models import Activity, Lead


def test_deleting_leads_in_bulk_removes_their_activities(app, client):
    client.post("/api/leads", json={"company": "A"})
    client.post("/api/leads", json={"company": "B"})
    assert Activity.query.count() == 2

    Lead.query.delete()          # bulk delete skips the ORM cascade; the database must do it
    db.session.commit()
    assert Activity.query.count() == 0


def test_seed_force_does_not_leave_stale_activity(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["seed-demo"]).exit_code == 0
    assert runner.invoke(args=["seed-demo"]).exit_code != 0            # refuses without --force
    assert runner.invoke(args=["seed-demo", "--force"]).exit_code == 0

    leads = Lead.query.count()
    assert leads == 12
    assert Activity.query.count() == leads                              # one "created" entry each

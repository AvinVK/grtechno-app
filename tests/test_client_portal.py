"""The client portal (kohal, 2026-10-22: "clients should be able to login... client should only be able
to see the projects they belong to") - a customer's own, read-only view of their project(s). See
app/client_portal.py and auth.visible_projects' own "client" branch."""

from app.extensions import db
from app.models import Client, Project
from conftest import make_user, signed_in


def make_client(name="Kalyani Cold Storage"):
    c = Client(name=name)
    db.session.add(c)
    db.session.commit()
    return c.id


def make_project_for(client_id, title="Fire NOC work", site_name="Plant 2"):
    p = Project(client_id=client_id, title=title, site_name=site_name)
    db.session.add(p)
    db.session.commit()
    return p.id


def client_user(app, client_id, name="Kalyani Contact", pin="285193"):
    user = make_user(name, pin=pin, role="client")
    user.client_id = client_id
    db.session.commit()
    return signed_in(app, user)


def test_only_a_client_role_can_use_the_portal(client, admin_client, accounts_client):
    for who in (client, admin_client, accounts_client):
        assert who.get("/my-projects").status_code == 403
        assert who.get("/api/my-projects").status_code == 403


def test_a_client_sees_only_their_own_projects(app):
    with app.app_context():
        mine = make_client("Kalyani Cold Storage")
        theirs = make_client("Orchid Heights CHS")
        my_pid = make_project_for(mine, title="Fire NOC work")
        make_project_for(theirs, title="Sprinkler AMC")
        who = client_user(app, mine)
    data = who.get("/api/my-projects").get_json()
    assert [p["id"] for p in data["projects"]] == [my_pid]
    assert data["projects"][0]["title"] == "Fire NOC work"


def test_a_client_with_no_client_id_sees_an_empty_list_not_an_error(app):
    with app.app_context():
        user = make_user("Stray Client", pin="285193", role="client")
        who = signed_in(app, user)
    data = who.get("/api/my-projects").get_json()
    assert data["projects"] == []


def test_a_client_cannot_fetch_someone_elses_project(app):
    with app.app_context():
        mine = make_client("Kalyani Cold Storage")
        theirs = make_client("Orchid Heights CHS")
        make_project_for(mine)
        their_pid = make_project_for(theirs, title="Sprinkler AMC")
        who = client_user(app, mine)
    assert who.get(f"/api/my-projects/{their_pid}").status_code == 404


def test_a_clients_own_project_detail_shape(app):
    with app.app_context():
        mine = make_client("Kalyani Cold Storage")
        pid = make_project_for(mine, title="Fire NOC work", site_name="Plant 2")
        who = client_user(app, mine)
    data = who.get(f"/api/my-projects/{pid}").get_json()["project"]
    assert data["id"] == pid and data["title"] == "Fire NOC work" and data["site_name"] == "Plant 2"
    assert data["status"] == "planned" and data["code"] == f"PRJ-{pid:04d}"


def test_a_clients_own_project_shows_the_same_stage_progress_the_admin_set(app, admin_client):
    """kohal, 2026-10-22: "stages of project, work pics at each phase" - a client's own project detail now
    carries the same fixed checklist as the admin's Progress tab (app/projects.py), read-only. Updated via
    admin_client (the real write path) rather than poking the DB directly, so this also proves the two
    sides of Project.stage_rows agree."""
    with app.app_context():
        mine = make_client("Kalyani Cold Storage")
        pid = make_project_for(mine, title="Fire NOC work")
        who = client_user(app, mine)
    admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"days": 5, "done": True})
    admin_client.patch(f"/api/projects/{pid}/stages/riser_installation", json={"days": 3})

    data = who.get(f"/api/my-projects/{pid}").get_json()
    stages = {s["key"]: s for s in data["stages"]}
    assert len(data["stages"]) == 9
    assert stages["commencement"]["days"] == 5
    assert stages["commencement"]["done"] is True and stages["commencement"]["completed_at"] is not None
    assert stages["riser_installation"]["days"] == 3


def test_a_clients_own_project_shows_which_stage_is_current_and_why_its_paused(app, admin_client):
    """kohal, 2026-10-22: "add pause button after each stage... follow the same template as lead" - a
    client sees the same one-stage-at-a-time picture, including why work has stalled."""
    with app.app_context():
        mine = make_client("Kalyani Cold Storage")
        pid = make_project_for(mine, title="Fire NOC work")
        who = client_user(app, mine)
    assert who.get(f"/api/my-projects/{pid}").get_json()["current_stage_key"] == "commencement"

    admin_client.post(f"/api/projects/{pid}/stages/commencement/pause", json={"reason": "material_shortage"})
    data = who.get(f"/api/my-projects/{pid}").get_json()
    stages = {s["key"]: s for s in data["stages"]}
    assert stages["commencement"]["paused"] is True
    assert stages["commencement"]["pause_reason"] == "material_shortage"


def test_a_clients_own_project_shows_the_admins_note_on_the_current_stage(app, admin_client):
    """kohal, 2026-10-22: "add note at each step"."""
    with app.app_context():
        mine = make_client("Kalyani Cold Storage")
        pid = make_project_for(mine, title="Fire NOC work")
        who = client_user(app, mine)
    admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"remarks": "Waiting on building diagram"})

    data = who.get(f"/api/my-projects/{pid}").get_json()
    stages = {s["key"]: s for s in data["stages"]}
    assert stages["commencement"]["remarks"] == "Waiting on building diagram"


def test_a_clients_own_project_shows_the_scheduled_payment_and_whether_its_paid(app, admin_client):
    """kohal, 2026-10-22: "give an option of adding 'add sheduled payment' checkbox after every step...
    until then it should show please pay for the project to move to next step" - the client is exactly who
    that message is for."""
    with app.app_context():
        mine = make_client("Kalyani Cold Storage")
        pid = make_project_for(mine, title="Fire NOC work")
        who = client_user(app, mine)
    admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"payment_required": True, "payment_amount": 15000})

    unpaid = who.get(f"/api/my-projects/{pid}").get_json()
    stages = {s["key"]: s for s in unpaid["stages"]}
    assert stages["commencement"]["payment_required"] is True
    assert stages["commencement"]["payment_amount"] == 15000.0
    assert stages["commencement"]["payment_received"] is False

    admin_client.patch(f"/api/projects/{pid}/stages/commencement", json={"payment_received": True})
    paid = who.get(f"/api/my-projects/{pid}").get_json()
    stages2 = {s["key"]: s for s in paid["stages"]}
    assert stages2["commencement"]["payment_received"] is True


def test_a_client_never_reaches_the_normal_projects_api(app):
    """auth.visible_projects' own "client" branch is only ever exercised through this portal - the
    ordinary Projects module stays check_module-gated, which a client role has no access to at all."""
    with app.app_context():
        mine = make_client("Kalyani Cold Storage")
        pid = make_project_for(mine)
        who = client_user(app, mine)
    assert who.get("/api/projects").status_code == 403
    assert who.get(f"/api/projects/{pid}").status_code == 403

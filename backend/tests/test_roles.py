"""Project roles: the permission matrix, how each role is held to it, and tenant isolation."""

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from helpers import open_triage, with_template
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from studio.db import SessionLocal, engine
from studio.models import AuditEvent, Project, ProjectMember, User
from studio.permissions import Permission, Role, allows

# Who may do what. A change here is a product decision: the test makes it visible.
EXPECTED = {
    Role.VIEWER: {"view"},
    Role.EDITOR: {"view", "edit", "run"},
    Role.ADMIN: {
        "view",
        "edit",
        "run",
        "delete_workflow",
        "manage_members",
        "manage_connections",
        "view_audit",
    },
    Role.OWNER: {p.value for p in Permission},
}


@pytest.mark.parametrize("role", list(Role))
def test_the_permission_matrix(role):
    assert {p.value for p in Permission if allows(role, p)} == EXPECTED[role]


def test_a_viewer_can_look_but_not_touch(seeded, make_client):
    carol = make_client("carol@acme.test")
    workflow = open_triage(carol)
    wid, pid = workflow["id"], workflow["project_id"]
    assert carol.get(f"/api/workflows/{wid}/versions").status_code == 200

    attempts = {
        "save": carol.put(f"/api/workflows/{wid}", json=with_template(workflow, "route", "x")),
        "run": carol.post(f"/api/workflows/{wid}/executions", json={"input": "hi"}),
        "restore": carol.post(
            f"/api/workflows/{wid}/restore", json={"revision": 1, "base_revision": 1}
        ),
        "delete workflow": carol.delete(f"/api/workflows/{wid}"),
        "create workflow": carol.post(f"/api/projects/{pid}/workflows", json={"name": "Mine"}),
        "delete project": carol.delete(f"/api/projects/{pid}"),
    }
    assert {name: r.status_code for name, r in attempts.items()} == dict.fromkeys(attempts, 403)
    assert "viewer" in attempts["save"].json()["detail"]
    assert open_triage(carol)["revision"] == 1  # nothing changed

    with SessionLocal() as db:
        denied = list(db.scalars(select(AuditEvent).where(AuditEvent.outcome == "denied")))
    assert len(denied) == len(attempts)
    assert {e.details["role"] for e in denied} == {"viewer"}
    assert {e.details["permission"] for e in denied} == {
        "edit",
        "run",
        "delete_workflow",
        "delete_project",
    }


def test_an_editor_can_build_and_run_but_not_delete(seeded, make_client):
    bob = make_client("bob@acme.test")
    workflow = open_triage(bob)
    wid = workflow["id"]
    assert bob.put(f"/api/workflows/{wid}", json=with_template(workflow, "route", "x")).is_success
    assert bob.post(f"/api/workflows/{wid}/executions", json={"input": "hi"}).status_code == 202
    assert bob.delete(f"/api/workflows/{wid}").status_code == 403
    assert bob.delete(f"/api/projects/{workflow['project_id']}").status_code == 403


def test_the_owner_can_delete_the_project(seeded, make_client):
    alice = make_client("alice@acme.test")
    project_id = open_triage(alice)["project_id"]
    assert alice.delete(f"/api/projects/{project_id}").status_code == 204


def test_whoever_creates_a_project_owns_it_and_nobody_else_sees_it(seeded, make_client):
    carol, alice = make_client("carol@acme.test"), make_client("alice@acme.test")
    created = carol.post("/api/projects", json={"name": "Carol's experiments"}).json()
    assert created["role"] == "owner" and "delete_project" in created["permissions"]
    workflow = carol.post(f"/api/projects/{created['id']}/workflows", json={"name": "Try"}).json()

    # Alice is in the same organization, but not in this project.
    assert "Carol's experiments" not in [p["name"] for p in alice.get("/api/projects").json()]
    assert alice.get(f"/api/projects/{created['id']}").status_code == 404
    assert alice.get(f"/api/workflows/{workflow['id']}").status_code == 404


def test_another_organization_gets_404_for_everything(seeded, make_client):
    alice, dave = make_client("alice@acme.test"), make_client("dave@globex.test")
    workflow = open_triage(alice)
    wid, pid = workflow["id"], workflow["project_id"]
    responses = [
        dave.get(f"/api/projects/{pid}"),
        dave.get(f"/api/workflows/{wid}"),
        dave.get(f"/api/workflows/{wid}/versions"),
        dave.put(f"/api/workflows/{wid}", json=with_template(workflow, "route", "x")),
        dave.post(f"/api/workflows/{wid}/executions", json={"input": "hi"}),
        dave.delete(f"/api/projects/{pid}"),
    ]
    assert [r.status_code for r in responses] == [404] * len(responses)


def test_the_database_refuses_a_membership_across_organizations(seeded):
    with SessionLocal() as db:
        dave = db.scalar(select(User).where(User.email == "dave@globex.test"))
        support = db.scalar(select(Project).where(Project.name == "Support Bot"))
        for org_id in (support.org_id, dave.org_id):  # whichever organization is claimed
            db.add(
                ProjectMember(project_id=support.id, user_id=dave.id, org_id=org_id, role="owner")
            )
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()


def test_the_migration_keeps_everyone_working(database):
    """Before roles, everyone in an organization could do everything. After the
    migration, each project's creator owns it and everyone else edits it."""
    alembic = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.downgrade(alembic, "0003")
    try:
        org, alice, bob, project = (uuid.uuid4() for _ in range(4))
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO organizations (id, name) VALUES (:o, 'A')"), {"o": org})
            for uid, email in ((alice, "a@acme.test"), (bob, "b@acme.test")):
                conn.execute(
                    text(
                        "INSERT INTO users (id, org_id, email, display_name, password_hash,"
                        " is_org_admin) VALUES (:u, :o, :e, :e, 'x', false)"
                    ),
                    {"u": uid, "o": org, "e": email},
                )
            conn.execute(
                text(
                    "INSERT INTO projects (id, org_id, name, created_by) VALUES (:p, :o, 'P', :a)"
                ),
                {"p": project, "o": org, "a": alice},
            )
        command.upgrade(alembic, "0004")
        with SessionLocal() as db:
            roles = {m.user_id: m.role for m in db.scalars(select(ProjectMember))}
        assert roles == {alice: "owner", bob: "editor"}
    finally:
        command.upgrade(alembic, "head")

"""The audit trail: what gets recorded, what never does, and that it can't be rewritten."""

import time

import pytest
from fastapi.testclient import TestClient
from helpers import open_triage, with_template
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from studio import audit
from studio.db import SessionLocal
from studio.main import app
from studio.models import AuditEvent, User


def events(action: str | None = None) -> list[AuditEvent]:
    with SessionLocal() as db:
        query = select(AuditEvent).order_by(AuditEvent.occurred_at)
        if action:
            query = query.where(AuditEvent.action == action)
        return list(db.scalars(query))


def user(email: str) -> User:
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.email == email))


def test_a_save_is_recorded_with_who_what_and_its_request_id(seeded, make_client):
    alice = make_client("alice@acme.test")
    workflow = open_triage(alice)
    body = with_template(workflow, "route", "Route to: billing") | {"message": "billing queue"}
    response = alice.put(f"/api/workflows/{workflow['id']}", json=body)

    [event] = events("workflow.update")
    assert event.outcome == "success"
    assert event.actor_name == "Alice" and event.org_id == user("alice@acme.test").org_id
    assert (event.resource_type, event.resource_name) == ("workflow", "Ticket triage")
    assert str(event.project_id) == workflow["project_id"]
    assert event.details == {"from_revision": 1, "revision": 2, "message": "billing queue"}
    assert event.request_id == response.headers["x-request-id"]
    assert event.source_ip is None  # only sign-ins keep an address


def test_a_failed_sign_in_is_recorded_without_the_password(seeded):
    client = TestClient(app, headers={"X-Requested-With": "studio"})
    wrong = client.post("/api/auth/login", json={"email": "alice@acme.test", "password": "hunter2"})
    unknown = client.post(
        "/api/auth/login", json={"email": "my-password-oops", "password": "hunter2"}
    )
    assert wrong.status_code == unknown.status_code == 401

    tried_alice, tried_unknown = events("auth.login")
    alice = user("alice@acme.test")
    assert tried_alice.outcome == "failure" and tried_alice.actor_id is None
    assert (tried_alice.resource_type, tried_alice.resource_id) == ("user", str(alice.id))
    assert tried_alice.org_id == alice.org_id  # Acme's admins will see it
    assert tried_alice.source_ip == "testclient"
    assert tried_unknown.org_id is None  # no tenant sees sign-ins to accounts that don't exist
    with SessionLocal() as db:
        stored = db.execute(text("SELECT row_to_json(audit_events)::text FROM audit_events"))
        everything = " ".join(row[0] for row in stored)
    assert "hunter2" not in everything and "my-password-oops" not in everything


def test_a_rejected_save_is_recorded_even_though_its_transaction_rolls_back(seeded, make_client):
    alice, bob = make_client("alice@acme.test"), make_client("bob@acme.test")
    alices, bobs = open_triage(alice), open_triage(bob)
    alice.put(f"/api/workflows/{alices['id']}", json=with_template(alices, "route", "A"))
    rejected = bob.put(f"/api/workflows/{bobs['id']}", json=with_template(bobs, "clean", "B"))
    assert rejected.status_code == 409

    accepted, refused = events("workflow.update")
    assert (accepted.actor_name, accepted.outcome) == ("Alice", "success")
    assert (refused.actor_name, refused.outcome) == ("Bob", "failure")
    assert refused.details == {
        "reason": "stale revision",
        "base_revision": 1,
        "current_revision": 2,
    }


def test_an_event_commits_only_with_the_change_it_describes(seeded):
    alice = user("alice@acme.test")
    with SessionLocal() as db:
        audit.record(db, "workflow.update", alice)
        db.rollback()  # the change failed, so it never happened
    assert events("workflow.update") == []


def test_runs_and_deletions_stay_on_record_after_the_workflow_is_gone(seeded, make_client):
    alice = make_client("alice@acme.test")
    workflow = open_triage(alice)
    run = alice.post(f"/api/workflows/{workflow['id']}/executions", json={"input": "hi"}).json()
    for _ in range(50):
        if alice.get(f"/api/executions/{run['id']}").json()["status"] == "succeeded":
            break
        time.sleep(0.05)
    assert alice.delete(f"/api/workflows/{workflow['id']}").status_code == 204

    [started], [finished] = events("execution.start"), events("execution.finish")
    assert started.resource_id == finished.resource_id == run["id"]
    assert started.details == {"revision": 1}  # the input itself is never recorded
    assert finished.details == {"status": "succeeded", "revision": 1}
    assert started.request_id == finished.request_id  # the run belongs to the request
    [deleted] = events("workflow.delete")
    assert (deleted.actor_name, deleted.resource_name) == ("Alice", "Ticket triage")


def test_audit_events_cannot_be_changed_or_removed(seeded, make_client):
    make_client("alice@acme.test")  # leaves an auth.login event
    for statement in (
        "UPDATE audit_events SET actor_name = 'Mallory'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ):
        with SessionLocal() as db, pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(statement))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_metadata_is_redacted_and_bounded():
    clean = audit.redact(
        {
            "password": "hunter2",
            "api_key": "sk-123",
            "headers": {"Authorization": "Bearer abc", "Accept": "json"},
            "note": "x" * 2000,
            "items": list(range(500)),
        }
    )
    assert clean["password"] == clean["api_key"] == "[redacted]"
    assert clean["headers"] == {"Authorization": "[redacted]", "Accept": "json"}
    assert len(clean["note"]) == 500 and len(clean["items"]) == 50


def test_request_ids_from_a_proxy_are_kept_only_if_they_look_like_ids():
    client = TestClient(app)
    kept = client.get("/api/health", headers={"X-Request-ID": "lb-2f9c41d07a"})
    replaced = client.get("/api/health", headers={"X-Request-ID": "<script>alert(1)</script>"})
    assert kept.headers["x-request-id"] == "lb-2f9c41d07a"
    assert len(replaced.headers["x-request-id"]) == 32

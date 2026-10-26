"""Optimistic concurrency, version history and restore, against a real PostgreSQL."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from helpers import open_triage, with_template
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from studio import versions
from studio.db import SessionLocal
from studio.models import User, Workflow, WorkflowRevision


def test_a_stale_save_is_rejected_and_nothing_is_overwritten(seeded, make_client):
    alice, bob = make_client("alice@acme.test"), make_client("bob@acme.test")
    alices, bobs = open_triage(alice), open_triage(bob)  # both load revision 1

    first = alice.put(f"/api/workflows/{alices['id']}", json=with_template(alices, "route", "A"))
    second = bob.put(f"/api/workflows/{bobs['id']}", json=with_template(bobs, "clean", "B"))

    assert first.status_code == 200 and first.json()["revision"] == 2
    assert second.status_code == 409
    assert second.json()["detail"]["current_revision"] == 2
    assert second.json()["detail"]["updated_by"] == "Alice"
    latest = open_triage(alice)
    route = next(n for n in latest["graph"]["nodes"] if n["id"] == "route")
    assert route["data"]["template"] == "A"  # Alice's change survived


def test_concurrent_saves_through_the_api_have_exactly_one_winner(seeded, make_client):
    # Alice in two browser tabs, and Bob: the same person can conflict with herself.
    clients = [make_client(e) for e in ("alice@acme.test", "alice@acme.test", "bob@acme.test")]
    loaded = [open_triage(c) for c in clients]
    start = threading.Barrier(len(clients))

    def save(i: int) -> int:
        start.wait()  # release all saves at the same moment
        body = with_template(loaded[i], "route", f"edit {i}")
        return clients[i].put(f"/api/workflows/{loaded[i]['id']}", json=body).status_code

    with ThreadPoolExecutor(len(clients)) as pool:
        codes = sorted(pool.map(save, range(len(clients))))

    assert codes == [200, 409, 409]
    with SessionLocal() as db:
        revisions = db.scalars(select(WorkflowRevision.revision)).all()
    assert sorted(revisions) == [1, 2]  # one snapshot per successful save, no gaps


def test_the_second_writer_waits_for_the_row_lock_then_sees_the_new_revision(seeded):
    """The race, step by step: A's UPDATE holds the row lock until A commits. B's UPDATE
    waits, then PostgreSQL re-checks `revision = 1` against A's committed row: no match."""
    with SessionLocal() as setup:
        workflow_id = setup.scalar(select(Workflow.id))
        alice = setup.scalar(select(User).where(User.display_name == "Alice"))
        bob = setup.scalar(select(User).where(User.display_name == "Bob"))
    a_updated, outcome = threading.Event(), {}

    def writer_a():
        with SessionLocal() as db:
            versions.save(
                db, db.get(Workflow, workflow_id), alice, "A", {"nodes": [], "edges": []}, 1
            )
            a_updated.set()
            time.sleep(0.5)  # hold the lock while B tries
            db.commit()

    def writer_b():
        a_updated.wait()
        with SessionLocal() as db:
            started = time.monotonic()
            try:
                versions.save(
                    db, db.get(Workflow, workflow_id), bob, "B", {"nodes": [], "edges": []}, 1
                )
            except versions.StaleRevision as stale:
                outcome["stale"] = stale
            outcome["waited"] = time.monotonic() - started

    threads = [threading.Thread(target=writer_a), threading.Thread(target=writer_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcome["stale"].current_revision == 2
    assert outcome["stale"].updated_by == "Alice"
    assert outcome["waited"] >= 0.4  # B really blocked on A's lock


def test_revision_numbers_are_unique_per_workflow(seeded):
    with SessionLocal() as db, pytest.raises(IntegrityError):
        workflow = db.scalar(select(Workflow))
        author = db.get(User, workflow.updated_by)
        versions.record(db, workflow.id, 1, author, "dup", {}, None, parent=None)


def test_history_compare_and_restore(seeded, make_client):
    alice = make_client("alice@acme.test")
    v1 = open_triage(alice)
    body = with_template(v1, "route", "{input}\n\nRoute to: billing")
    body["message"] = "Send billing tickets to billing\n\x00"
    v2 = alice.put(f"/api/workflows/{v1['id']}", json=body).json()

    history = alice.get(f"/api/workflows/{v1['id']}/versions").json()
    assert [h["revision"] for h in history] == [2, 1]
    assert history[0]["author"] == "Alice"
    assert history[0]["message"] == "Send billing tickets to billing"  # control chars removed
    assert history[0]["parent_revision"] == 1

    changes = alice.get(f"/api/workflows/{v1['id']}/compare", params={"base": 1, "head": 2}).json()
    assert changes["nodes_changed"]["route"]["template"][1] == "{input}\n\nRoute to: billing"
    assert changes["nodes_added"] == [] and changes["edges_added"] == []

    restored = alice.post(
        f"/api/workflows/{v1['id']}/restore", json={"revision": 1, "base_revision": 2}
    ).json()
    assert restored["revision"] == 3  # a new revision; 1 and 2 are untouched
    assert restored["graph"] == v1["graph"]
    history = alice.get(f"/api/workflows/{v1['id']}/versions").json()
    assert [(h["revision"], h["message"]) for h in history][0] == (3, "Restored revision 1")
    assert alice.get(f"/api/workflows/{v1['id']}/executions").json() == []  # nothing ran
    assert v2["revision"] == 2


def test_restore_from_a_stale_revision_is_a_conflict_too(seeded, make_client):
    alice, bob = make_client("alice@acme.test"), make_client("bob@acme.test")
    v1 = open_triage(alice)
    alice.put(f"/api/workflows/{v1['id']}", json=with_template(v1, "route", "x"))
    response = bob.post(
        f"/api/workflows/{v1['id']}/restore", json={"revision": 1, "base_revision": 1}
    )
    assert response.status_code == 409


def test_other_tenants_cannot_read_history(seeded, make_client):
    workflow = open_triage(make_client("alice@acme.test"))
    dave = make_client("dave@globex.test")
    assert dave.get(f"/api/workflows/{workflow['id']}/versions").status_code == 404
    assert dave.get(f"/api/workflows/{workflow['id']}/versions/1").status_code == 404


def test_runs_execute_the_revision_they_started_with(seeded, make_client):
    alice = make_client("alice@acme.test")
    v1 = open_triage(alice)
    with SessionLocal() as db:  # nothing else in this test touches the revision table
        assert db.execute(text("SELECT count(*) FROM workflow_revisions")).scalar() == 1
    run = alice.post(f"/api/workflows/{v1['id']}/executions", json={"input": "hi"}).json()
    assert run["revision"] == 1

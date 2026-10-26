"""Reading the audit trail: who may, what they see, and what an export contains."""

import csv
import io
from datetime import UTC, datetime, timedelta

from helpers import open_triage, with_template


def test_only_organization_admins_can_read_the_audit_log(seeded, make_client):
    bob = make_client("bob@acme.test")  # an ordinary member
    assert bob.get("/api/audit-logs").status_code == 403
    assert bob.get("/api/audit-logs/export").status_code == 403
    alice = make_client("alice@acme.test")
    event_id = alice.get("/api/audit-logs").json()["items"][0]["id"]
    assert bob.get(f"/api/audit-logs/{event_id}").status_code == 403


def test_each_organization_sees_only_its_own_events(seeded, make_client):
    alice, dave = make_client("alice@acme.test"), make_client("dave@globex.test")
    acme = alice.get("/api/audit-logs").json()
    globex = dave.get("/api/audit-logs").json()
    assert {e["actor_name"] for e in acme["items"]} == {"Alice"}
    assert {e["actor_name"] for e in globex["items"]} == {"Dave"}
    # Even with an id in hand, or a filter naming Acme's project, Dave gets nothing.
    assert dave.get(f"/api/audit-logs/{acme['items'][0]['id']}").status_code == 404
    project_id = open_triage(alice)["project_id"]
    assert dave.get("/api/audit-logs", params={"project_id": project_id}).json()["total"] == 0


def test_filters_narrow_the_results(seeded, make_client):
    alice, bob = make_client("alice@acme.test"), make_client("bob@acme.test")
    alices, bobs = open_triage(alice), open_triage(bob)
    alice.put(f"/api/workflows/{alices['id']}", json=with_template(alices, "route", "A"))
    bob.put(f"/api/workflows/{bobs['id']}", json=with_template(bobs, "clean", "B"))  # 409

    def find(**params) -> list[dict]:
        return alice.get("/api/audit-logs", params=params).json()["items"]

    [refused] = find(outcome="failure")
    assert (refused["actor_name"], refused["action"]) == ("Bob", "workflow.update")
    assert len(find(action="workflow.update")) == 2
    assert {e["actor_name"] for e in find(actor_id=refused["actor_id"])} == {"Bob"}
    assert len(find(resource_type="workflow", resource_id=alices["id"])) == 2
    assert {e["resource_name"] for e in find(q="TRIAGE")} == {"Ticket triage"}
    assert find(q="%") == []  # a literal percent sign, not a wildcard
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert find(since=tomorrow) == []
    assert len(find(until=tomorrow)) == alice.get("/api/audit-logs").json()["total"]
    assert alice.get("/api/audit-logs", params={"since": "2026-01-01T00:00"}).status_code == 422


def test_pages_cover_every_event_exactly_once(seeded, make_client):
    alice = make_client("alice@acme.test")
    for _ in range(6):
        make_client("bob@acme.test")
    total = alice.get("/api/audit-logs").json()["total"]
    assert total == 7
    seen = []
    for offset in range(0, total, 3):
        page = alice.get("/api/audit-logs", params={"limit": 3, "offset": offset}).json()
        seen += [e["id"] for e in page["items"]]
    assert len(seen) == len(set(seen)) == total

    by_actor = alice.get("/api/audit-logs", params={"sort": "actor_name", "order": "asc"})
    assert [e["actor_name"] for e in by_actor.json()["items"]] == ["Alice"] + ["Bob"] * 6


def test_one_event_shows_its_details(seeded, make_client):
    alice = make_client("alice@acme.test")
    workflow = open_triage(alice)
    body = with_template(workflow, "route", "x") | {"message": "try billing"}
    saved = alice.put(f"/api/workflows/{workflow['id']}", json=body)
    [item] = alice.get("/api/audit-logs", params={"action": "workflow.update"}).json()["items"]
    detail = alice.get(f"/api/audit-logs/{item['id']}").json()
    assert detail["metadata"] == {"from_revision": 1, "revision": 2, "message": "try billing"}
    assert detail["request_id"] == saved.headers["x-request-id"]
    assert detail["project_name"] == "Support Bot"


def test_the_export_is_safe_to_open_in_a_spreadsheet_and_is_itself_recorded(seeded, make_client):
    alice = make_client("alice@acme.test")
    project_id = open_triage(alice)["project_id"]
    evil = '=HYPERLINK("http://evil.test","Click")'
    alice.post(f"/api/projects/{project_id}/workflows", json={"name": evil})

    export = alice.get("/api/audit-logs/export", params={"action": "workflow.create"})
    assert export.headers["content-type"].startswith("text/csv")
    assert "attachment" in export.headers["content-disposition"]
    header, row = list(csv.reader(io.StringIO(export.text)))
    assert row[header.index("resource_name")] == "'" + evil
    assert row[header.index("action")] == "workflow.create"

    [recorded] = alice.get("/api/audit-logs", params={"action": "audit.export"}).json()["items"]
    detail = alice.get(f"/api/audit-logs/{recorded['id']}").json()
    assert detail["metadata"] == {"rows": 1, "filters": {"action": "workflow.create"}}

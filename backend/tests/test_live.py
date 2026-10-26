"""The live channel: presence, save notices, and who may listen."""

import json

import pytest
from fastapi.testclient import TestClient
from helpers import open_triage, project_id, with_template
from starlette.websockets import WebSocketDisconnect

from studio.main import app
from studio.routes import live as live_routes

ORIGIN = "http://localhost:3000"


@pytest.fixture
def studio():
    """One client, so sockets and requests share an event loop, as on a real server.
    Each call says who is calling with that person's session cookie."""
    with TestClient(app, headers={"X-Requested-With": "studio"}) as client:
        yield client


def session(email: str) -> dict[str, str]:
    login = TestClient(app).post(
        "/api/auth/login",
        json={"email": email, "password": "studio-demo"},
        headers={"X-Requested-With": "studio"},
    )
    return {"cookie": f"studio_session={login.cookies['studio_session']}"}


def channel(studio, workflow_id: str, who: dict, origin: str = ORIGIN):
    return studio.websocket_connect(
        f"/api/workflows/{workflow_id}/live", headers=who | {"origin": origin}
    )


def people(ws) -> list[dict]:
    message = ws.receive_json()
    assert message["type"] == "presence"
    return message["people"]


def refused(studio, workflow_id: str, who: dict, origin: str = ORIGIN) -> int:
    with pytest.raises(WebSocketDisconnect) as closed:
        with channel(studio, workflow_id, who, origin) as ws:
            ws.receive_json()
    return closed.value.code


@pytest.fixture
def triage(seeded, make_client) -> dict:
    return open_triage(make_client("alice@acme.test"))


def test_people_see_each_other_and_who_is_editing(studio, triage):
    alice, bob = session("alice@acme.test"), session("bob@acme.test")
    with channel(studio, triage["id"], bob) as bobs:
        [me] = people(bobs)
        assert (me["name"], me["initials"], me["you"]) == ("Bob", "B", True)
        with channel(studio, triage["id"], alice) as alices:
            here = people(bobs)
            assert [(p["name"], p["you"]) for p in here] == [("Bob", True), ("Alice", False)]
            assert "@" not in json.dumps(here)  # names and initials, never emails
            people(alices)
            alices.send_text(json.dumps({"type": "editing", "editing": True}))
            assert {p["name"]: p["editing"] for p in people(bobs)} == {"Bob": False, "Alice": True}
        assert [p["name"] for p in people(bobs)] == ["Bob"]  # Alice left


def test_a_save_reaches_everyone_once_it_is_committed(studio, triage):
    alice, bob = session("alice@acme.test"), session("bob@acme.test")
    with channel(studio, triage["id"], alice) as alices:
        people(alices)
        body = with_template(triage, "route", "Route to: billing")
        assert studio.put(f"/api/workflows/{triage['id']}", json=body, headers=bob).is_success
        assert alices.receive_json() == {"type": "saved", "revision": 2, "by": "Bob"}
        latest = studio.get(f"/api/workflows/{triage['id']}", headers=alice).json()
        assert latest["revision"] == 2  # already loadable when the notice arrives


def test_viewers_never_show_up_as_editing(studio, triage):
    with channel(studio, triage["id"], session("carol@acme.test")) as ws:
        people(ws)
        ws.send_text(json.dumps({"type": "editing", "editing": True}))
        assert people(ws)[0]["editing"] is False


def test_only_our_own_pages_and_project_members_may_listen(studio, triage):
    assert refused(studio, triage["id"], session("alice@acme.test"), "https://evil.test") == 4403
    assert refused(studio, triage["id"], {}) == 4404  # signed out
    assert refused(studio, triage["id"], session("erin@acme.test")) == 4404  # not in the project
    assert refused(studio, triage["id"], session("dave@globex.test")) == 4404  # other tenant


def test_someone_removed_from_the_project_loses_the_channel(
    studio, triage, make_client, monkeypatch
):
    monkeypatch.setattr(live_routes, "RECHECK_SECONDS", 0.2)
    alice = make_client("alice@acme.test")
    pid = project_id(alice)
    carol_id = next(
        m["user_id"]
        for m in alice.get(f"/api/projects/{pid}/members").json()
        if m["display_name"] == "Carol"
    )
    with channel(studio, triage["id"], session("carol@acme.test")) as ws:
        people(ws)
        assert alice.delete(f"/api/projects/{pid}/members/{carol_id}").status_code == 204
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4404


def test_a_flood_of_messages_closes_the_socket(studio, triage):
    with channel(studio, triage["id"], session("bob@acme.test")) as ws:
        people(ws)
        with pytest.raises(WebSocketDisconnect) as closed:
            for i in range(40):
                ws.send_text(json.dumps({"type": "editing", "editing": i % 2 == 0}))
            while True:
                ws.receive_json()
    assert closed.value.code == 4429

"""Members, role changes, invitations, and the limits on sign-in attempts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from helpers import add_user, open_triage, project_id, with_template
from sqlalchemy import text, update

from studio.db import SessionLocal
from studio.models import Invitation


def invite(client, email: str, role: str = "editor") -> str:
    """Invites someone to Support Bot and returns the token from the link."""
    r = client.post(
        f"/api/projects/{project_id(client)}/invitations", json={"email": email, "role": role}
    )
    assert r.status_code == 201, r.text
    return r.json()["link"].split("#", 1)[1]


def accept(client, token: str):
    return client.post("/api/invitations/accept", json={"token": token})


def test_an_invited_person_joins_with_the_role_they_were_invited_to(seeded, make_client):
    alice = make_client("alice@acme.test")
    token = invite(alice, "Erin@Acme.test", "editor")  # addresses are compared lower-case

    erin = make_client("erin@acme.test")
    assert erin.get("/api/projects").json() == []
    joined = accept(erin, token)
    assert joined.status_code == 200 and joined.json()["role"] == "editor"
    workflow = open_triage(erin)
    saved = erin.put(f"/api/workflows/{workflow['id']}", json=with_template(workflow, "route", "x"))
    assert saved.status_code == 200
    with SessionLocal() as db:  # only a hash of the token is ever stored
        stored = db.execute(text("SELECT row_to_json(invitations)::text FROM invitations"))
        assert token not in " ".join(row[0] for row in stored)


def test_a_link_works_once_and_only_for_the_invited_account(seeded, make_client):
    add_user("eve@globex.test", org="Globex")
    token = invite(make_client("alice@acme.test"), "erin@acme.test")

    bob, eve, erin = (
        make_client(e) for e in ("bob@acme.test", "eve@globex.test", "erin@acme.test")
    )
    assert accept(bob, token).status_code == 404  # someone else in the organization
    assert accept(eve, token).status_code == 404  # someone in another organization
    assert accept(erin, "x" * 43).status_code == 404  # a made-up link
    assert accept(erin, token).status_code == 200
    assert accept(erin, token).status_code == 404  # used up
    assert "Support Bot" not in [p["name"] for p in eve.get("/api/projects").json()]


def test_revoked_replaced_and_expired_links_stop_working(seeded, make_client):
    for email in ("frank@acme.test", "gina@acme.test"):  # Erin is in the demo data
        add_user(email)
    alice = make_client("alice@acme.test")
    pid = project_id(alice)

    revoked = invite(alice, "erin@acme.test")
    [pending] = alice.get(f"/api/projects/{pid}/invitations").json()
    assert alice.delete(f"/api/projects/{pid}/invitations/{pending['id']}").status_code == 204
    assert accept(make_client("erin@acme.test"), revoked).status_code == 404

    replaced = invite(alice, "frank@acme.test")
    newer = invite(alice, "frank@acme.test")  # the second invitation replaces the first
    frank = make_client("frank@acme.test")
    assert accept(frank, replaced).status_code == 404
    assert accept(frank, newer).status_code == 200

    expired = invite(alice, "gina@acme.test")
    with SessionLocal.begin() as db:
        db.execute(update(Invitation).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    assert accept(make_client("gina@acme.test"), expired).status_code == 404
    assert alice.get(f"/api/projects/{pid}/invitations").json() == []


def test_one_link_accepted_twice_at_the_same_moment_has_one_winner(seeded, make_client):
    token = invite(make_client("alice@acme.test"), "erin@acme.test")
    tabs = [make_client("erin@acme.test") for _ in range(2)]
    start = Barrier(2)

    def go(tab) -> int:
        start.wait()
        return accept(tab, token).status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(go, tabs)) == [200, 404]


def test_inviting_someone_already_in_the_project_is_refused(seeded, make_client):
    alice = make_client("alice@acme.test")
    r = alice.post(
        f"/api/projects/{project_id(alice)}/invitations",
        json={"email": "bob@acme.test", "role": "viewer"},
    )
    assert r.status_code == 409


def test_editors_and_viewers_cannot_manage_members(seeded, make_client):
    bob, alice = make_client("bob@acme.test"), make_client("alice@acme.test")
    pid = project_id(bob)
    carol_id = next(m["user_id"] for m in alice.get(f"/api/projects/{pid}/members").json()
                    if m["display_name"] == "Carol")  # fmt: skip
    attempts = [
        bob.post(
            f"/api/projects/{pid}/invitations", json={"email": "x@acme.test", "role": "admin"}
        ),
        bob.patch(f"/api/projects/{pid}/members/{carol_id}", json={"role": "editor"}),
        bob.delete(f"/api/projects/{pid}/members/{carol_id}"),
        bob.get(f"/api/projects/{pid}/invitations"),
    ]
    assert [r.status_code for r in attempts] == [403] * 4
    # Members see each other's names; only people who manage members see addresses.
    assert {m["email"] for m in bob.get(f"/api/projects/{pid}/members").json()} == {None}
    assert None not in {m["email"] for m in alice.get(f"/api/projects/{pid}/members").json()}


def test_admins_manage_everyone_but_owners(seeded, make_client):
    alice = make_client("alice@acme.test")
    pid = project_id(alice)
    ids = {
        m["display_name"]: m["user_id"] for m in alice.get(f"/api/projects/{pid}/members").json()
    }

    def set_role(client, name: str, role: str) -> int:
        return client.patch(f"/api/projects/{pid}/members/{ids[name]}", json={"role": role})

    assert set_role(alice, "Carol", "admin").status_code == 200
    carol = make_client("carol@acme.test")
    assert set_role(carol, "Bob", "viewer").status_code == 200
    assert set_role(carol, "Bob", "owner").status_code == 403  # can't hand out ownership
    assert set_role(carol, "Alice", "editor").status_code == 403  # can't touch an owner
    assert carol.delete(f"/api/projects/{pid}/members/{ids['Alice']}").status_code == 403


def test_a_project_always_keeps_an_owner(seeded, make_client):
    alice = make_client("alice@acme.test")
    pid = project_id(alice)
    ids = {
        m["display_name"]: m["user_id"] for m in alice.get(f"/api/projects/{pid}/members").json()
    }

    me = f"/api/projects/{pid}/members/{ids['Alice']}"
    assert alice.patch(me, json={"role": "admin"}).status_code == 409
    assert alice.delete(me).status_code == 409
    # Once someone else owns it too, Alice may step down.
    alice.patch(f"/api/projects/{pid}/members/{ids['Carol']}", json={"role": "owner"})
    assert alice.patch(me, json={"role": "admin"}).status_code == 200


def test_members_can_leave(seeded, make_client):
    carol = make_client("carol@acme.test")
    pid = project_id(carol)
    me = next(
        m for m in carol.get(f"/api/projects/{pid}/members").json() if m["display_name"] == "Carol"
    )
    assert carol.delete(f"/api/projects/{pid}/members/{me['user_id']}").status_code == 204
    assert carol.get("/api/projects").json() == []


def test_project_admins_read_their_own_projects_audit_log(seeded, make_client):
    alice, carol = make_client("alice@acme.test"), make_client("carol@acme.test")
    pid = project_id(alice)
    assert carol.get("/api/audit-logs", params={"project_id": pid}).status_code == 403  # viewer
    carol_id = next(m["user_id"] for m in alice.get(f"/api/projects/{pid}/members").json()
                    if m["display_name"] == "Carol")  # fmt: skip
    alice.patch(f"/api/projects/{pid}/members/{carol_id}", json={"role": "admin"})

    events = carol.get("/api/audit-logs", params={"project_id": pid}).json()["items"]
    assert events and {e["project_id"] for e in events} == {pid}
    assert carol.get("/api/audit-logs").status_code == 403  # not the whole organization
    sign_in = alice.get("/api/audit-logs", params={"action": "auth.login"}).json()["items"][0]
    assert carol.get(f"/api/audit-logs/{sign_in['id']}").status_code == 403  # no project


def test_password_guessing_is_slowed_down(seeded, make_client):
    from fastapi.testclient import TestClient

    from studio.main import app

    client = TestClient(app, headers={"X-Requested-With": "studio"})
    guess = {"email": "alice@acme.test", "password": "wrong"}
    assert [client.post("/api/auth/login", json=guess).status_code for _ in range(10)] == [401] * 10
    blocked = client.post("/api/auth/login", json=guess | {"password": "studio-demo"})
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0

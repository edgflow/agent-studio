"""OAuth connections: the authorization code flow with PKCE, encrypted storage,
who may see and manage a connection, and revocation."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlsplit

from helpers import open_triage, project_id, with_template
from sqlalchemy import select, text, update

from devtools import oauth_provider
from studio import crypto
from studio.db import SessionLocal
from studio.models import AuditEvent, Connection, OAuthState

CALLBACK = "http://localhost:3000/api/connections/local/callback"


def start(client, project: str | None = None) -> dict:
    r = client.post("/api/connections/local/start", json={"project_id": project})
    assert r.status_code == 200, r.text
    return dict(parse_qsl(urlsplit(r.json()["authorize_url"]).query))


def consent(browser, query: dict, decision: str = "allow") -> str:
    """The person on the provider's page clicks Authorize (or Cancel). Returns the
    path and query the provider sends their browser back to."""
    url = "http://oauth.test/authorize?" + "&".join(f"{k}={v}" for k, v in query.items())
    assert browser.get("/authorize", params=query).status_code == 200, url
    fields = {k: query[k] for k in ("redirect_uri", "state", "code_challenge", "scope")}
    back = browser.post("/authorize", data=fields | {"decision": decision}, follow_redirects=False)
    location = urlsplit(back.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == CALLBACK
    return f"{location.path}?{location.query}"


def come_back(client, callback: str) -> str:
    """Follows the provider's redirect into our callback; returns where we send them next."""
    r = client.get(callback, follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"]


def connect(client, browser, project: str | None = None) -> dict:
    assert come_back(client, consent(browser, start(client, project))).endswith("connected=local")
    path = f"/api/projects/{project}/connections" if project else "/api/connections"
    [connection] = client.get(path).json()
    return connection


def test_connecting_stores_an_encrypted_token_that_works(seeded, make_client, provider):
    alice = make_client("alice@acme.test")
    connection = connect(alice, provider)
    assert connection["account_login"] == "dev-octocat"
    assert connection["scopes"] == ["read:user"] and connection["status"] == "active"

    [issued] = oauth_provider.tokens  # the token the provider handed out
    with SessionLocal() as db:
        row = db.scalar(select(Connection))
        raw = db.execute(text("SELECT row_to_json(connections)::text FROM connections")).scalar()
    assert issued not in raw  # not in the database in readable form
    assert crypto.decrypt(row.access_token) == issued  # but we can use it
    assert issued not in alice.get("/api/connections").text  # and the API never shows it


def test_a_callback_works_once_and_only_for_whoever_started_it(seeded, make_client, provider):
    alice, bob = make_client("alice@acme.test"), make_client("bob@acme.test")
    callback = consent(provider, start(alice))
    # Bob is tricked into opening Alice's callback link: it must not connect anything.
    assert come_back(bob, callback).endswith("error=invalid_state")
    assert come_back(alice, callback).endswith("error=invalid_state")  # it was used up
    assert alice.get("/api/connections").json() == bob.get("/api/connections").json() == []


def test_cancelling_at_the_provider_connects_nothing(seeded, make_client, provider):
    alice = make_client("alice@acme.test")
    callback = consent(provider, start(alice), decision="deny")
    assert come_back(alice, callback).endswith("error=cancelled")
    assert alice.get("/api/connections").json() == []
    with SessionLocal() as db:
        failed = db.scalar(select(AuditEvent).where(AuditEvent.action == "connection.create"))
    assert failed.outcome == "failure" and failed.details["reason"] == "declined at the provider"


def test_an_abandoned_attempt_expires(seeded, make_client, provider):
    alice = make_client("alice@acme.test")
    callback = consent(provider, start(alice))
    with SessionLocal.begin() as db:
        db.execute(update(OAuthState).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert come_back(alice, callback).endswith("error=expired")


def test_a_stolen_code_is_useless_without_the_verifier(seeded, make_client, provider):
    alice = make_client("alice@acme.test")
    callback = consent(provider, start(alice))
    code = dict(parse_qsl(urlsplit(callback).query))["code"]
    stolen = provider.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CALLBACK,
            "client_id": "agent-studio-dev",
            "client_secret": "test-only-secret",
            "code_verifier": "a guess",
        },
    )
    assert stolen.json()["error"] == "invalid_grant"
    assert oauth_provider.tokens == {}


def test_the_redirect_uri_is_fixed_whatever_the_request_says(seeded, make_client, provider):
    alice = make_client("alice@acme.test")
    r = alice.post("/api/connections/local/start", json={}, headers={"Host": "evil.test"})
    assert dict(parse_qsl(urlsplit(r.json()["authorize_url"]).query))["redirect_uri"] == CALLBACK
    # And the provider refuses to send a code anywhere it doesn't know.
    query = start(alice) | {"redirect_uri": "https://evil.test/steal"}
    assert provider.get("/authorize", params=query).status_code == 400


def test_a_personal_connection_is_invisible_to_everyone_else(seeded, make_client, provider):
    alice, bob = make_client("alice@acme.test"), make_client("bob@acme.test")
    connection = connect(alice, provider)
    assert bob.get("/api/connections").json() == []
    assert bob.post(f"/api/connections/{connection['id']}/test").status_code == 404
    assert bob.delete(f"/api/connections/{connection['id']}").status_code == 404


def test_a_shared_connection_is_seen_by_members_and_managed_by_admins(
    seeded, make_client, provider
):
    alice, bob = make_client("alice@acme.test"), make_client("bob@acme.test")
    dave = make_client("dave@globex.test")
    pid = project_id(alice)
    shared_start = bob.post("/api/connections/local/start", json={"project_id": pid})
    assert shared_start.status_code == 403  # an editor can't add one

    connection = connect(alice, provider, project=pid)
    assert connection["owner"] == "project"
    assert [c["id"] for c in bob.get(f"/api/projects/{pid}/connections").json()] == [
        connection["id"]
    ]
    assert bob.delete(f"/api/connections/{connection['id']}").status_code == 403
    assert dave.get(f"/api/projects/{pid}/connections").status_code == 404
    assert dave.delete(f"/api/connections/{connection['id']}").status_code == 404


def test_disconnecting_revokes_the_token_at_the_provider(seeded, make_client, provider):
    alice = make_client("alice@acme.test")
    connection = connect(alice, provider)
    [issued] = oauth_provider.tokens

    result = alice.delete(f"/api/connections/{connection['id']}").json()
    assert result["revoked_at_provider"] is True
    assert provider.get("/user", headers={"Authorization": f"Bearer {issued}"}).status_code == 401
    assert alice.get("/api/connections").json() == []


def test_a_token_revoked_elsewhere_shows_up_as_invalid(seeded, make_client, provider):
    alice = make_client("alice@acme.test")
    connection = connect(alice, provider)
    oauth_provider.tokens.clear()  # e.g. revoked in the provider's own settings page
    checked = alice.post(f"/api/connections/{connection['id']}/test").json()
    assert checked["status"] == "invalid"


def test_a_workflow_refuses_to_store_credentials(seeded, make_client):
    bob = make_client("bob@acme.test")
    workflow = open_triage(bob)
    body = with_template(workflow, "route", "x")
    body["graph"]["nodes"][1]["data"]["github_token"] = "anything"
    assert bob.put(f"/api/workflows/{workflow['id']}", json=body).status_code == 422
    pasted = with_template(workflow, "route", "Use " + "ghp_" + "a1" * 18 + " to call GitHub")
    rejected = bob.put(f"/api/workflows/{workflow['id']}", json=pasted)
    assert rejected.status_code == 422 and "connection" in rejected.text

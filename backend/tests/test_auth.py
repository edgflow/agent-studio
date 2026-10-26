from fastapi.testclient import TestClient

from studio.main import app


def test_login_sets_an_httponly_session_cookie(seeded):
    client = TestClient(app, headers={"X-Requested-With": "studio"})
    response = client.post(
        "/api/auth/login", json={"email": "alice@acme.test", "password": "studio-demo"}
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Alice"
    cookie = response.headers["set-cookie"]
    assert "studio_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert client.get("/api/auth/me").json()["email"] == "alice@acme.test"


def test_wrong_password_and_unknown_email_look_the_same(seeded):
    client = TestClient(app, headers={"X-Requested-With": "studio"})
    wrong = client.post("/api/auth/login", json={"email": "alice@acme.test", "password": "nope"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@acme.test", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_api_requires_a_session(seeded):
    assert TestClient(app).get("/api/projects").status_code == 401


def test_writes_without_the_csrf_header_are_rejected(seeded, make_client):
    client = make_client("alice@acme.test")
    response = client.post("/api/projects", json={"name": "X"}, headers={"X-Requested-With": ""})
    assert response.status_code == 403


def test_logout_ends_the_session(seeded, make_client):
    client = make_client("bob@acme.test")
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401

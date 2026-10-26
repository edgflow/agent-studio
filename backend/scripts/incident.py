"""A small incident, then the question every admin asks: uv run python scripts/incident.py

Someone guesses at Alice's password, then Bob creates a workflow called
"Escalations" and deletes it again. Afterwards Alice, an organization admin,
tries to find out what happened. Needs the backend and the demo data.
"""

import httpx

API = "http://127.0.0.1:8000/api"
HEADERS = {"X-Requested-With": "studio"}


def client() -> httpx.Client:
    return httpx.Client(base_url=API, headers=HEADERS)


def signed_in(email: str) -> httpx.Client:
    c = client()
    c.post("/auth/login", json={"email": email, "password": "studio-demo"}).raise_for_status()
    return c


# 1. Three wrong passwords for Alice's account.
for guess in ("123456", "password", "alice2026"):
    r = client().post("/auth/login", json={"email": "alice@acme.test", "password": guess})
    print(f"login as alice with a guessed password -> {r.status_code}")

# 2. Bob creates a workflow and deletes it.
bob = signed_in("bob@acme.test")
project = next(p for p in bob.get("/projects").json() if p["name"] == "Support Bot")
created = bob.post(f"/projects/{project['id']}/workflows", json={"name": "Escalations"}).json()
deleted = bob.delete(f"/workflows/{created['id']}")
print(f"someone deletes the 'Escalations' workflow -> {deleted.status_code}")

# 3. Alice investigates.
alice = signed_in("alice@acme.test")
r = alice.get("/audit-logs", params={"limit": 10})
print(f"\nAlice asks the API for the audit log -> {r.status_code}")
if r.status_code == 200:
    for e in reversed(r.json()["items"]):
        when, who, what = e["occurred_at"][11:19], e["actor_name"] or "unknown", e["action"]
        print(f"  {when}  {e['outcome']:8} {what:22} {who:8} {e['resource_name'] or ''}")

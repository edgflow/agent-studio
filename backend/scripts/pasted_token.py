"""What happens to a token pasted into a workflow: uv run python scripts/pasted_token.py

Bob wants his workflow to read GitHub issues, so he pastes his personal access
token into a node's settings. Needs the backend and fresh demo data.
"""

import httpx
from sqlalchemy import text

from studio.db import SessionLocal

API = "http://127.0.0.1:8000/api"
TOKEN = "ghp_" + "demo" * 9  # looks like a GitHub token; isn't one


def signed_in(email: str) -> httpx.Client:
    c = httpx.Client(base_url=API, headers={"X-Requested-With": "studio"})
    c.post("/auth/login", json={"email": email, "password": "studio-demo"}).raise_for_status()
    return c


def open_triage(client: httpx.Client) -> dict:
    project = next(p for p in client.get("/projects").json() if p["name"] == "Support Bot")
    summary = client.get(f"/projects/{project['id']}/workflows").json()[0]
    return client.get(f"/workflows/{summary['id']}").json()


def save(client: httpx.Client, workflow: dict, data: dict) -> httpx.Response:
    graph = workflow["graph"]
    next(n for n in graph["nodes"] if n["id"] == "clean")["data"] = data
    body = {"name": workflow["name"], "graph": graph, "base_revision": workflow["revision"]}
    return client.put(f"/workflows/{workflow['id']}", json=body)


def token_seen_by(client: httpx.Client, graph: dict) -> str:
    found = [v for n in graph["nodes"] for v in n["data"].values() if v == TOKEN]
    return f"{TOKEN[:12]}…" if found else "nothing"


bob, carol = signed_in("bob@acme.test"), signed_in("carol@acme.test")
workflow = open_triage(bob)
template = {"template": "Customer ticket:\n{input}"}

r = save(bob, workflow, template | {"github_token": TOKEN})
detail = r.json().get("detail") if r.status_code != 200 else ""
print(f"bob pastes his GitHub token into a node and saves -> {r.status_code}")
if detail:
    print(f"  {detail[0]['msg'] if isinstance(detail, list) else detail}")
saved_revision = r.json()["revision"] if r.status_code == 200 else None

seen = token_seen_by(carol, open_triage(carol)["graph"])
print(f"carol (viewer) opens the workflow and sees: {seen}")

if saved_revision:
    r = save(bob, open_triage(bob), template)
    print(f"bob realises, removes the token and saves -> {r.status_code}")
    old = carol.get(f"/workflows/{workflow['id']}/versions/{saved_revision}").json()
    seen = token_seen_by(carol, old["graph"])
    print(f"carol opens revision {saved_revision} from the history: {seen}")

with SessionLocal() as db:
    rows = db.scalar(
        text("SELECT count(*) FROM workflow_revisions WHERE graph::text LIKE :t"),
        {"t": f"%{TOKEN}%"},
    )
print(f"revisions holding the token in plain text in the database: {rows}")

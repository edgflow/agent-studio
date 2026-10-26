"""What a read-only contractor can do: uv run python scripts/contractor.py

Carol joined Acme last week to review prompts in the Support Bot project. She
should be able to look, not touch. Needs the backend and fresh demo data
(the last step deletes the project).
"""

import httpx

API = "http://127.0.0.1:8000/api"


def signed_in(email: str) -> httpx.Client:
    c = httpx.Client(base_url=API, headers={"X-Requested-With": "studio"})
    c.post("/auth/login", json={"email": email, "password": "studio-demo"}).raise_for_status()
    return c


def show(what: str, r: httpx.Response) -> None:
    detail = r.json().get("detail") if r.content else None
    print(f"{what:44} -> {r.status_code} {detail if isinstance(detail, str) else ''}".rstrip())


carol = signed_in("carol@acme.test")
project = next(p for p in carol.get("/projects").json() if p["name"] == "Support Bot")
summary = carol.get(f"/projects/{project['id']}/workflows").json()[0]
workflow = carol.get(f"/workflows/{summary['id']}").json()
role = project.get("role", "none, everyone can do everything")
print(f"Carol opens '{workflow['name']}' (her role: {role})")

graph = workflow["graph"]
graph["nodes"][1]["data"]["template"] = "Carol was here: {input}"
show(
    "carol saves a change to the workflow",
    carol.put(
        f"/workflows/{workflow['id']}",
        json={"name": workflow["name"], "graph": graph, "base_revision": workflow["revision"]},
    ),
)
show(
    "carol starts a run (paid model calls)",
    carol.post(f"/workflows/{workflow['id']}/executions", json={"input": "hello"}),
)
show("carol deletes the whole 'Support Bot' project", carol.delete(f"/projects/{project['id']}"))

alice = signed_in("alice@acme.test")
left = [p["name"] for p in alice.get("/projects").json()]
print(f"\nAlice's projects afterwards: {left or 'none'}")

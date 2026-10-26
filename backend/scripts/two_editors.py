"""Two people edit the same workflow at the same time: uv run python scripts/two_editors.py

Alice and Bob both open "Ticket triage". Alice renames the route; Bob, still
looking at the version he opened, changes the intro text and saves after her.
Prints what each save returned and what the workflow looks like afterwards.
Needs the backend on http://127.0.0.1:8000 and the demo data.
"""

import httpx

API = "http://127.0.0.1:8000/api"
HEADERS = {"X-Requested-With": "studio"}


def login(email: str) -> httpx.Client:
    client = httpx.Client(base_url=API, headers=HEADERS)
    client.post("/auth/login", json={"email": email, "password": "studio-demo"}).raise_for_status()
    return client


def edit(workflow: dict, node_id: str, template: str) -> dict:
    graph = workflow["graph"]
    for node in graph["nodes"]:
        if node["id"] == node_id:
            node["data"]["template"] = template
    body = {"name": workflow["name"], "graph": graph}
    if "revision" in workflow:  # sent once the API knows about revisions
        body["base_revision"] = workflow["revision"]
    return body


def template_of(workflow: dict, node_id: str) -> str:
    return next(n["data"]["template"] for n in workflow["graph"]["nodes"] if n["id"] == node_id)


alice, bob = login("alice@acme.test"), login("bob@acme.test")
project = next(p for p in alice.get("/projects").json() if p["name"] == "Support Bot")
workflow_id = alice.get(f"/projects/{project['id']}/workflows").json()[0]["id"]

alices_copy = alice.get(f"/workflows/{workflow_id}").json()  # both open the workflow
bobs_copy = bob.get(f"/workflows/{workflow_id}").json()

r1 = alice.put(
    f"/workflows/{workflow_id}",
    json=edit(alices_copy, "route", "{input}\n\nRoute to: billing queue"),
)
print(f"Alice saves the new route  -> {r1.status_code}")
r2 = bob.put(
    f"/workflows/{workflow_id}", json=edit(bobs_copy, "clean", "Ticket from a customer:\n{input}")
)
detail = r2.json().get("detail", "") if r2.is_error else ""
print(f"Bob saves the new intro    -> {r2.status_code}  {detail}")

final = alice.get(f"/workflows/{workflow_id}").json()
print("Afterwards:")
print(f"  intro: {template_of(final, 'clean')!r}")
print(f"  route: {template_of(final, 'route')!r}")

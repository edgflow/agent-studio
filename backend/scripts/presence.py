"""Who else is in here? uv run python scripts/presence.py [--via-frontend]

Alice and Bob open the same workflow. Bob keeps the live channel open while
Alice starts editing and saves. What does Bob learn, and when? Needs the
backend (and with --via-frontend, the Next.js dev server) and fresh demo data.
"""

import json
import sys
from contextlib import ExitStack

import httpx
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

API = "http://127.0.0.1:8000/api"
ORIGIN = "http://localhost:3000"
LIVE = "ws://localhost:3000/api" if "--via-frontend" in sys.argv else "ws://127.0.0.1:8000/api"


def signed_in(email: str) -> httpx.Client:
    c = httpx.Client(base_url=API, headers={"X-Requested-With": "studio"})
    c.post("/auth/login", json={"email": email, "password": "studio-demo"}).raise_for_status()
    return c


def live(client: httpx.Client, workflow_id: str):
    cookie = f"studio_session={client.cookies['studio_session']}"
    return connect(
        f"{LIVE}/workflows/{workflow_id}/live",
        additional_headers={"Cookie": cookie, "Origin": ORIGIN},
    )


def show(message: str) -> None:
    event = json.loads(message)
    if event["type"] == "presence":
        people = ", ".join(
            f"{p['name']}{' (editing)' if p['editing'] else ''}{' = you' if p['you'] else ''}"
            for p in event["people"]
        )
        print(f"  bob's screen: here now: {people}")
    elif event["type"] == "saved":
        print(f"  bob's screen: {event['by']} saved revision {event['revision']}")


alice, bob = signed_in("alice@acme.test"), signed_in("bob@acme.test")
project = next(p for p in bob.get("/projects").json() if p["name"] == "Support Bot")
workflow_id = bob.get(f"/projects/{project['id']}/workflows").json()[0]["id"]
workflow = bob.get(f"/workflows/{workflow_id}").json()
print(f"Bob opens '{workflow['name']}' at revision {workflow['revision']}")

sockets = ExitStack()  # closes every live connection at the end
try:
    bob_live = sockets.enter_context(live(bob, workflow_id))
except InvalidStatus as refused:
    bob_live = None
    print(
        f"Bob's editor asks who else is here -> HTTP {refused.response.status_code}: no way to know"
    )

if bob_live:
    show(bob_live.recv(timeout=3))
    alice_live = sockets.enter_context(live(alice, workflow_id))
    print("Alice opens the same workflow")
    show(bob_live.recv(timeout=3))
    alice_live.send(json.dumps({"type": "editing", "editing": True}))
    print("Alice starts changing the routing text")
    show(bob_live.recv(timeout=3))

graph = alice.get(f"/workflows/{workflow_id}").json()["graph"]
graph["nodes"][2]["data"]["template"] = "{input}\n\nRoute to: billing"
saved = alice.put(
    f"/workflows/{workflow_id}",
    json={"name": workflow["name"], "graph": graph, "base_revision": workflow["revision"]},
).json()
print(f"Alice saves revision {saved['revision']}")
if bob_live:
    while (message := json.loads(bob_live.recv(timeout=3)))["type"] != "saved":
        pass
    show(json.dumps(message))
    print("Bob reloads before he changes anything: no conflict, no lost work")
else:
    graph = workflow["graph"]
    graph["nodes"][1]["data"]["template"] = "Ticket from a customer:\n{input}"
    late = bob.put(
        f"/workflows/{workflow_id}",
        json={"name": workflow["name"], "graph": graph, "base_revision": workflow["revision"]},
    )
    print(f"Bob, after twenty minutes of work, saves -> {late.status_code}")
    print("  only now does he learn that Alice changed it first")
sockets.close()

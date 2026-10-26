GRAPH = {
    "nodes": [
        {"id": "in", "type": "input", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "out", "type": "output", "position": {"x": 200, "y": 0}, "data": {}},
    ],
    "edges": [{"id": "in-out", "source": "in", "target": "out"}],
}


def support_project(client) -> str:
    return next(p["id"] for p in client.get("/api/projects").json() if p["name"] == "Support Bot")


def test_create_open_and_save_a_workflow(seeded, make_client):
    alice = make_client("alice@acme.test")
    project = support_project(alice)
    created = alice.post(f"/api/projects/{project}/workflows", json={"name": "Summarizer"}).json()
    assert created["graph"] == {"nodes": [], "edges": []}

    saved = alice.put(
        f"/api/workflows/{created['id']}", json={"name": "Summarizer", "graph": GRAPH}
    )
    assert saved.status_code == 200
    assert (
        alice.get(f"/api/workflows/{created['id']}").json()["graph"]["edges"][0]["target"] == "out"
    )


def test_invalid_graphs_are_rejected(seeded, make_client):
    alice = make_client("alice@acme.test")
    project = support_project(alice)
    workflow = alice.post(f"/api/projects/{project}/workflows", json={"name": "Broken"}).json()
    bad = {
        "nodes": GRAPH["nodes"],
        "edges": [{"id": "x", "source": "in", "target": "missing"}],
    }
    response = alice.put(f"/api/workflows/{workflow['id']}", json={"name": "Broken", "graph": bad})
    assert response.status_code == 422


def test_other_organizations_cannot_see_or_touch_workflows(seeded, make_client):
    alice = make_client("alice@acme.test")
    dave = make_client("dave@globex.test")  # Globex, a different tenant
    project = support_project(alice)
    workflow = alice.get(f"/api/projects/{project}/workflows").json()[0]["id"]

    assert dave.get(f"/api/projects/{project}/workflows").status_code == 404
    assert dave.get(f"/api/workflows/{workflow}").status_code == 404
    assert (
        dave.put(f"/api/workflows/{workflow}", json={"name": "x", "graph": GRAPH}).status_code
        == 404
    )
    assert "Support Bot" not in [p["name"] for p in dave.get("/api/projects").json()]

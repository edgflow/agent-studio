"""Shared steps for tests that edit the demo workflow."""

import copy


def open_triage(client) -> dict:
    project = next(p for p in client.get("/api/projects").json() if p["name"] == "Support Bot")
    workflow_id = client.get(f"/api/projects/{project['id']}/workflows").json()[0]["id"]
    return client.get(f"/api/workflows/{workflow_id}").json()


def with_template(workflow: dict, node_id: str, template: str) -> dict:
    graph = copy.deepcopy(workflow["graph"])
    for node in graph["nodes"]:
        if node["id"] == node_id:
            node["data"]["template"] = template
    return {"name": workflow["name"], "graph": graph, "base_revision": workflow["revision"]}

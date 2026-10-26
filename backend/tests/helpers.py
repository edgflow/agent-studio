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


def add_user(email: str, org: str = "Acme AI") -> None:
    """A user in an organization, in no project yet. Password: studio-demo."""
    from sqlalchemy import select

    from studio.db import SessionLocal
    from studio.models import Organization, User
    from studio.security import hash_password

    with SessionLocal() as db:
        org_id = db.scalar(select(Organization.id).where(Organization.name == org))
        name = email.split("@")[0].title()
        db.add(
            User(
                org_id=org_id,
                email=email,
                display_name=name,
                password_hash=hash_password("studio-demo"),
            )
        )
        db.commit()


def project_id(client) -> str:
    return next(p["id"] for p in client.get("/api/projects").json() if p["name"] == "Support Bot")

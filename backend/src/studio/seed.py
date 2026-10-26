"""Demo data for local development: uv run python -m studio.seed

Two organizations, so cross-tenant access can be demonstrated. Every demo
user's password is "studio-demo". Never run this against production.
"""

from sqlalchemy import select

from studio.db import SessionLocal
from studio.models import Organization, Project, User, Workflow
from studio.security import hash_password

DEMO_PASSWORD = "studio-demo"

TRIAGE_GRAPH = {
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "position": {"x": 0, "y": 120},
            "data": {"label": "Ticket"},
        },
        {
            "id": "clean",
            "type": "template",
            "position": {"x": 260, "y": 120},
            "data": {"template": "Customer ticket:\n{input}"},
        },
        {
            "id": "route",
            "type": "template",
            "position": {"x": 520, "y": 120},
            "data": {"template": "{input}\n\nRoute to: support queue"},
        },
        {"id": "out", "type": "output", "position": {"x": 780, "y": 120}, "data": {}},
    ],
    "edges": [
        {"id": "in-clean", "source": "in", "target": "clean"},
        {"id": "clean-route", "source": "clean", "target": "route"},
        {"id": "route-out", "source": "route", "target": "out"},
    ],
}


def seed() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == "alice@acme.test")):
            print("demo data already present")
            return
        acme = Organization(name="Acme AI")
        globex = Organization(name="Globex")
        db.add_all([acme, globex])
        db.flush()
        password = hash_password(DEMO_PASSWORD)
        users = {
            "alice": User(
                org_id=acme.id,
                email="alice@acme.test",
                display_name="Alice",
                password_hash=password,
                is_org_admin=True,
            ),
            "bob": User(
                org_id=acme.id,
                email="bob@acme.test",
                display_name="Bob",
                password_hash=password,
            ),
            "carol": User(
                org_id=acme.id,
                email="carol@acme.test",
                display_name="Carol",
                password_hash=password,
            ),
            "dave": User(
                org_id=globex.id,
                email="dave@globex.test",
                display_name="Dave",
                password_hash=password,
                is_org_admin=True,
            ),
        }
        db.add_all(users.values())
        db.flush()
        support = Project(org_id=acme.id, name="Support Bot", created_by=users["alice"].id)
        research = Project(org_id=globex.id, name="Research Agents", created_by=users["dave"].id)
        db.add_all([support, research])
        db.flush()
        db.add(
            Workflow(
                project_id=support.id,
                name="Ticket triage",
                graph=TRIAGE_GRAPH,
                created_by=users["alice"].id,
                updated_by=users["alice"].id,
            )
        )
        db.commit()
        print("demo data created; password for every user:", DEMO_PASSWORD)


if __name__ == "__main__":
    seed()

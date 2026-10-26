"""Tests run against a real PostgreSQL database, created fresh for each test session.

TEST_DATABASE_ADMIN_URL must point at a server where the user may create
databases (default: the local dev server). Tables are emptied before every
test, so tests see committed data exactly as the app does.
"""

import os
import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

ADMIN_URL = os.environ.get(
    "TEST_DATABASE_ADMIN_URL",
    "postgresql+psycopg://studio:studio@127.0.0.1:55433/postgres",
)
TEST_DB = f"studio_test_{os.getpid()}"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"

# Point the application at the test database before any studio module is imported.
os.environ["DATABASE_URL"] = TEST_URL
# A fresh encryption key per run, and the local OAuth provider (see the `provider` fixture).
os.environ["TOKEN_ENCRYPTION_KEYS"] = Fernet.generate_key().decode()
os.environ["DEV_OAUTH_URL"] = "http://oauth.test"
os.environ["DEV_OAUTH_CLIENT_SECRET"] = "test-only-secret"


@pytest.fixture(scope="session", autouse=True)
def database():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}"'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini")), "head")
    yield
    from studio.db import engine

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(autouse=True)
def clean_tables(database):
    from studio.db import Base, engine

    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        # audit_events refuses TRUNCATE. The table's owner can switch that off, which is
        # exactly why production runs the app as a role that doesn't own the table.
        conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_truncate"))
        conn.execute(text(f"TRUNCATE {names} CASCADE"))
        conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_truncate"))
    yield


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    from studio.ratelimit import limiter

    limiter.reset()


@pytest.fixture
def provider(monkeypatch):
    """The local OAuth provider, answering every call the backend makes to a provider.
    The returned client plays the person's browser on the provider's pages."""
    from fastapi.testclient import TestClient

    from devtools import oauth_provider
    from studio import providers

    oauth_provider.codes.clear()
    oauth_provider.tokens.clear()
    monkeypatch.setattr(providers, "http", lambda: TestClient(oauth_provider.app))
    return TestClient(oauth_provider.app)


@pytest.fixture
def seeded():
    """The demo organizations, users, project and workflow."""
    from studio.seed import seed

    seed()


@pytest.fixture
def make_client():
    """Returns a function that logs a demo user in and gives back their client."""
    from fastapi.testclient import TestClient

    from studio.main import app

    def login(email: str) -> TestClient:
        client = TestClient(app, headers={"X-Requested-With": "studio"})
        response = client.post("/api/auth/login", json={"email": email, "password": "studio-demo"})
        assert response.status_code == 200, response.text
        return client

    return login


def new_id() -> str:
    return str(uuid.uuid4())

"""Database models. Every timestamp is timezone-aware and stored in UTC."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from studio.db import Base


def now_column() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


class Organization(Base):
    """A tenant. Nothing is ever shared across organizations."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = now_column()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_org_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = now_column()


class AuthSession(Base):
    """A login session. Only a hash of the token is stored."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = now_column()

    user: Mapped[User] = relationship(lazy="joined")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = now_column()


class Workflow(Base):
    """A visual workflow: React Flow nodes and edges, stored as JSON."""

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=lambda: {"nodes": [], "edges": []})
    # Bumped by every save. A save must name the revision it started from.
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = now_column()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class WorkflowRevision(Base):
    """An immutable snapshot of a workflow, written by every save. Never updated or deleted."""

    __tablename__ = "workflow_revisions"
    __table_args__ = (UniqueConstraint("workflow_id", "revision"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    revision: Mapped[int]
    parent_revision: Mapped[int | None]  # the revision this one was edited from
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB)
    message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = now_column()


class Execution(Base):
    """One run of a workflow."""

    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int | None]  # the saved revision that ran
    started_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(
        String(20), default="queued"
    )  # queued, running, succeeded, failed, cancelled
    input: Mapped[str] = mapped_column(default="")
    output: Mapped[str | None]
    error: Mapped[str | None]
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = now_column()
    finished_at: Mapped[datetime | None]


class AuditEvent(Base):
    """One thing that happened: who did what to which resource, and with what outcome.

    Append-only: the application only inserts, and a database trigger rejects
    UPDATE and DELETE. Deliberately no foreign keys, so an event outlives the
    user, project or workflow it describes (names are copied in for that reason).
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("outcome IN ('success', 'failure', 'denied')", name="audit_outcome"),
        Index("ix_audit_org_time", "org_id", "occurred_at"),
        Index("ix_audit_org_action", "org_id", "action"),
        Index("ix_audit_org_actor", "org_id", "actor_id"),
        Index("ix_audit_org_project", "org_id", "project_id"),
        Index("ix_audit_org_resource", "org_id", "resource_type", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = now_column()
    org_id: Mapped[uuid.UUID | None]  # None only for sign-ins to unknown accounts
    project_id: Mapped[uuid.UUID | None]
    actor_id: Mapped[uuid.UUID | None]
    actor_name: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(64))  # e.g. "workflow.update"
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    resource_name: Mapped[str | None] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(String(10))
    request_id: Mapped[str | None] = mapped_column(String(64))
    source_ip: Mapped[str | None] = mapped_column(String(45))  # sign-in events only
    # "metadata" is reserved on SQLAlchemy models, hence the attribute name.
    details: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)

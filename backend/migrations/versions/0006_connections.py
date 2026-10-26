"""connections

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("account_login", sa.String(length=100), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("access_token", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token", sa.LargeBinary(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        created_at(),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        # Exactly one owner: a person or a project.
        sa.CheckConstraint("(user_id IS NULL) <> (project_id IS NULL)", name="connection_owner"),
        sa.CheckConstraint("status IN ('active', 'invalid')", name="connection_status"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_connections_project_id", "connections", ["project_id"])
    op.create_index("ix_connections_user_id", "connections", ["user_id"])
    op.create_index(
        "uq_connections_personal",
        "connections",
        ["provider", "user_id"],
        unique=True,
        postgresql_where="user_id IS NOT NULL",
    )
    op.create_index(
        "uq_connections_shared",
        "connections",
        ["provider", "project_id"],
        unique=True,
        postgresql_where="project_id IS NOT NULL",
    )
    op.create_table(
        "oauth_states",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("code_verifier", sa.LargeBinary(), nullable=False),
        created_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_hash"),
    )


def downgrade() -> None:
    op.drop_table("oauth_states")
    op.drop_table("connections")

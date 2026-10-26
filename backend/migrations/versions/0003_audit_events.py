"""audit events

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The database itself refuses to change or remove an audit event, whatever the
# application code does. (The table's owner can still disable the trigger: in
# production the app connects as a role that does not own this table.)
APPEND_ONLY = """
CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: % is not allowed', TG_OP;
END $$;

CREATE TRIGGER audit_events_no_update_or_delete
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();

CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only();
"""


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_name", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("resource_name", sa.String(length=200), nullable=True),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("outcome IN ('success', 'failure', 'denied')", name="audit_outcome"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Every query is scoped to one organization, so org_id leads every index.
    op.create_index("ix_audit_org_time", "audit_events", ["org_id", "occurred_at"])
    op.create_index("ix_audit_org_action", "audit_events", ["org_id", "action"])
    op.create_index("ix_audit_org_actor", "audit_events", ["org_id", "actor_id"])
    op.create_index("ix_audit_org_project", "audit_events", ["org_id", "project_id"])
    op.create_index(
        "ix_audit_org_resource", "audit_events", ["org_id", "resource_type", "resource_id"]
    )
    op.execute(APPEND_ONLY)


def downgrade() -> None:
    op.drop_table("audit_events")  # drops its triggers too
    op.execute("DROP FUNCTION audit_events_append_only()")

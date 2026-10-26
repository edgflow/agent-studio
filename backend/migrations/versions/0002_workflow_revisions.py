"""workflow revisions

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflows", sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_table(
        "workflow_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("parent_revision", sa.Integer(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "revision"),
    )
    # Every existing workflow starts with its current state as revision 1.
    op.execute(
        """
        INSERT INTO workflow_revisions
            (id, workflow_id, revision, author_id, name, graph, message, created_at)
        SELECT gen_random_uuid(), id, 1, updated_by, name, graph, 'Initial version', updated_at
        FROM workflows
        """
    )
    op.add_column("executions", sa.Column("revision", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("executions", "revision")
    op.drop_table("workflow_revisions")
    op.drop_column("workflows", "revision")

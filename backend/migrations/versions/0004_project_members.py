"""project members

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Until now everyone in an organization could do anything in its projects. Each
# project's creator becomes its owner and everyone else an editor: nobody loses
# their day-to-day work, and only owners keep the destructive powers. Owners can
# raise or lower roles from there.
BACKFILL = """
INSERT INTO project_members (project_id, user_id, org_id, role)
SELECT p.id, u.id, p.org_id, CASE WHEN u.id = p.created_by THEN 'owner' ELSE 'editor' END
FROM projects p JOIN users u ON u.org_id = p.org_id
"""


def upgrade() -> None:
    op.create_unique_constraint("uq_projects_id_org", "projects", ["id", "org_id"])
    op.create_unique_constraint("uq_users_id_org", "users", ["id", "org_id"])
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('owner', 'admin', 'editor', 'viewer')", name="member_role"),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["project_id", "org_id"], ["projects.id", "projects.org_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "org_id"], ["users.id", "users.org_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_table("project_members")
    op.drop_constraint("uq_users_id_org", "users", type_="unique")
    op.drop_constraint("uq_projects_id_org", "projects", type_="unique")

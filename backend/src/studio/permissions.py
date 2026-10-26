"""Who may do what in a project. Every rule lives here, and every route asks here.

Roles are ordered: each one can do everything the roles below it can.

    viewer  open workflows, their history and their runs
    editor  + create and save workflows, restore revisions, start and cancel runs
    admin   + delete workflows, manage members, read the project's audit log
    owner   + delete the project, make other owners
"""

import uuid
from enum import StrEnum

from fastapi import HTTPException
from sqlalchemy.orm import Session

from studio import audit
from studio.models import Project, ProjectMember, User


class Role(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"
    OWNER = "owner"


RANK = {Role.VIEWER: 1, Role.EDITOR: 2, Role.ADMIN: 3, Role.OWNER: 4}


class Permission(StrEnum):
    VIEW = "view"
    EDIT = "edit"
    RUN = "run"
    DELETE_WORKFLOW = "delete_workflow"
    MANAGE_MEMBERS = "manage_members"
    VIEW_AUDIT = "view_audit"
    DELETE_PROJECT = "delete_project"


# The lowest role that holds each permission.
MINIMUM_ROLE: dict[Permission, Role] = {
    Permission.VIEW: Role.VIEWER,
    Permission.EDIT: Role.EDITOR,
    Permission.RUN: Role.EDITOR,  # runs call paid models
    Permission.DELETE_WORKFLOW: Role.ADMIN,
    Permission.MANAGE_MEMBERS: Role.ADMIN,
    Permission.VIEW_AUDIT: Role.ADMIN,
    Permission.DELETE_PROJECT: Role.OWNER,
}


def allows(role: Role, permission: Permission) -> bool:
    return RANK[role] >= RANK[MINIMUM_ROLE[permission]]


def permissions_of(role: Role) -> list[Permission]:
    """What the frontend may offer this role. Only a hint: the backend checks every request."""
    return [p for p in Permission if allows(role, p)]


def role_in(db: Session, user: User, project_id: uuid.UUID) -> Role | None:
    member = db.get(ProjectMember, (project_id, user.id))
    return Role(member.role) if member else None


def authorize(
    db: Session,
    user: User,
    project: Project,
    permission: Permission,
    target: audit.Target | None = None,
    not_found: str = "project not found",
) -> Role:
    """The user's role in the project, if it allows `permission`.

    Not a member (or another organization's project): 404, as if the project didn't
    exist. A member whose role is too low: 403, and a permission.denied audit event.
    """
    role = role_in(db, user, project.id) if project.org_id == user.org_id else None
    if role is None:
        raise HTTPException(404, not_found)
    if not allows(role, permission):
        audit.record_now(
            "permission.denied",
            user,
            target=target or audit.Target.of(project),
            outcome="denied",
            details={"permission": permission.value, "role": role.value},
        )
        raise HTTPException(
            403, f"your role in this project ({role}) doesn't allow this ({permission})"
        )
    return role

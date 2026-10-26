"""Projects group the workflows of a team inside an organization."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from studio import audit
from studio.auth import CurrentUser
from studio.db import Db
from studio.models import Project, ProjectMember, User
from studio.permissions import Permission, Role, authorize, permissions_of, role_in

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    id: str
    name: str
    role: Role
    permissions: list[Permission]  # what the UI may offer; the API still checks every call

    @classmethod
    def of(cls, p: Project, role: Role) -> "ProjectOut":
        return cls(id=str(p.id), name=p.name, role=role, permissions=permissions_of(role))


def get_project(
    db: Db, user: User, project_id: uuid.UUID, permission: Permission = Permission.VIEW
) -> Project:
    """A project the user is a member of, with a role that allows `permission`."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    authorize(db, user, project, permission)
    return project


@router.get("")
def list_projects(db: Db, user: CurrentUser) -> list[ProjectOut]:
    """Only the projects the user is a member of."""
    rows = db.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user.id)
        .order_by(Project.name)
    )
    return [ProjectOut.of(p, Role(role)) for p, role in rows]


@router.post("", status_code=201)
def create_project(body: ProjectIn, db: Db, user: CurrentUser) -> ProjectOut:
    project = Project(org_id=user.org_id, name=body.name.strip(), created_by=user.id)
    db.add(project)
    db.flush()
    # Anyone in the organization may start a project, and owns what they start.
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            org_id=user.org_id,
            role=Role.OWNER,
            added_by=user.id,
        )
    )
    audit.record(db, "project.create", user, target=audit.Target.of(project))
    return ProjectOut.of(project, Role.OWNER)


@router.get("/{project_id}")
def read_project(project_id: uuid.UUID, db: Db, user: CurrentUser) -> ProjectOut:
    project = get_project(db, user, project_id)
    return ProjectOut.of(project, role_in(db, user, project.id))


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: uuid.UUID, db: Db, user: CurrentUser) -> None:
    project = get_project(db, user, project_id, Permission.DELETE_PROJECT)
    audit.record(db, "project.delete", user, target=audit.Target.of(project))
    db.delete(project)

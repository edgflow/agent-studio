"""Projects group the workflows of a team inside an organization."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from studio.auth import CurrentUser
from studio.db import Db
from studio.models import Project, User

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    id: str
    name: str

    @classmethod
    def of(cls, p: Project) -> "ProjectOut":
        return cls(id=str(p.id), name=p.name)


def get_project(db: Db, user: User, project_id: uuid.UUID) -> Project:
    """A project of the user's organization, or 404. Other tenants' projects don't exist for us."""
    project = db.get(Project, project_id)
    if project is None or project.org_id != user.org_id:
        raise HTTPException(404, "project not found")
    return project


@router.get("")
def list_projects(db: Db, user: CurrentUser) -> list[ProjectOut]:
    rows = db.scalars(select(Project).where(Project.org_id == user.org_id).order_by(Project.name))
    return [ProjectOut.of(p) for p in rows]


@router.post("", status_code=201)
def create_project(body: ProjectIn, db: Db, user: CurrentUser) -> ProjectOut:
    project = Project(org_id=user.org_id, name=body.name.strip(), created_by=user.id)
    db.add(project)
    db.flush()
    return ProjectOut.of(project)


@router.get("/{project_id}")
def read_project(project_id: uuid.UUID, db: Db, user: CurrentUser) -> ProjectOut:
    return ProjectOut.of(get_project(db, user, project_id))


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: uuid.UUID, db: Db, user: CurrentUser) -> None:
    db.delete(get_project(db, user, project_id))

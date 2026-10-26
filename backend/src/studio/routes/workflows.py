"""Workflows: create, open, save and delete."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from studio.auth import CurrentUser
from studio.db import Db
from studio.graph import Graph
from studio.models import Project, User, Workflow
from studio.routes.projects import get_project

router = APIRouter(prefix="/api", tags=["workflows"])


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkflowSave(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    graph: Graph


class WorkflowSummary(BaseModel):
    id: str
    name: str
    updated_at: datetime


class WorkflowOut(BaseModel):
    id: str
    project_id: str
    name: str
    graph: dict[str, Any]
    updated_at: datetime
    updated_by: str

    @classmethod
    def of(cls, w: Workflow, db: Db) -> "WorkflowOut":
        author = db.get(User, w.updated_by)
        return cls(
            id=str(w.id),
            project_id=str(w.project_id),
            name=w.name,
            graph=w.graph,
            updated_at=w.updated_at,
            updated_by=author.display_name if author else "unknown",
        )


def get_workflow(db: Db, user: User, workflow_id: uuid.UUID) -> Workflow:
    """A workflow in one of the user's organization's projects, or 404."""
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or db.get(Project, workflow.project_id).org_id != user.org_id:
        raise HTTPException(404, "workflow not found")
    return workflow


@router.get("/projects/{project_id}/workflows")
def list_workflows(project_id: uuid.UUID, db: Db, user: CurrentUser) -> list[WorkflowSummary]:
    get_project(db, user, project_id)
    rows = db.scalars(
        select(Workflow).where(Workflow.project_id == project_id).order_by(Workflow.name)
    )
    return [WorkflowSummary(id=str(w.id), name=w.name, updated_at=w.updated_at) for w in rows]


@router.post("/projects/{project_id}/workflows", status_code=201)
def create_workflow(
    project_id: uuid.UUID, body: WorkflowCreate, db: Db, user: CurrentUser
) -> WorkflowOut:
    get_project(db, user, project_id)
    workflow = Workflow(
        project_id=project_id,
        name=body.name.strip(),
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(workflow)
    db.flush()
    db.refresh(workflow)
    return WorkflowOut.of(workflow, db)


@router.get("/workflows/{workflow_id}")
def read_workflow(workflow_id: uuid.UUID, db: Db, user: CurrentUser) -> WorkflowOut:
    return WorkflowOut.of(get_workflow(db, user, workflow_id), db)


@router.put("/workflows/{workflow_id}")
def save_workflow(
    workflow_id: uuid.UUID, body: WorkflowSave, db: Db, user: CurrentUser
) -> WorkflowOut:
    workflow = get_workflow(db, user, workflow_id)
    workflow.name = body.name.strip()
    workflow.graph = body.graph.model_dump()
    workflow.updated_by = user.id
    db.flush()
    db.refresh(workflow)
    return WorkflowOut.of(workflow, db)


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: uuid.UUID, db: Db, user: CurrentUser) -> None:
    db.delete(get_workflow(db, user, workflow_id))

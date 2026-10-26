"""Workflows: create, open, save and delete."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from studio import audit, versions
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
    # The revision the editor loaded. The save fails with 409 if it is no longer the latest.
    base_revision: int = Field(ge=1)
    message: str | None = Field(default=None, max_length=500)


class WorkflowSummary(BaseModel):
    id: str
    name: str
    updated_at: datetime


class WorkflowOut(BaseModel):
    id: str
    project_id: str
    name: str
    graph: dict[str, Any]
    revision: int
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
            revision=w.revision,
            updated_at=w.updated_at,
            updated_by=author.display_name if author else "unknown",
        )


def get_workflow(db: Db, user: User, workflow_id: uuid.UUID) -> Workflow:
    """A workflow in one of the user's organization's projects, or 404."""
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or db.get(Project, workflow.project_id).org_id != user.org_id:
        raise HTTPException(404, "workflow not found")
    return workflow


def conflict(
    stale: versions.StaleRevision, action: str, user: User, workflow: Workflow, base: int
) -> HTTPException:
    """Records the rejected attempt, then builds the 409 with what the editor needs to
    explain the conflict and offer a reload."""
    audit.record_now(
        action,
        user,
        target=audit.Target.of(workflow),
        details={
            "reason": "stale revision",
            "base_revision": base,
            "current_revision": stale.current_revision,
        },
    )
    return HTTPException(
        409,
        {
            "message": f"{stale.updated_by} saved revision {stale.current_revision} "
            "after you opened this workflow",
            "current_revision": stale.current_revision,
            "updated_by": stale.updated_by,
            "updated_at": stale.updated_at.isoformat(),
        },
    )


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
    versions.record(db, workflow.id, 1, user, workflow.name, workflow.graph, "Created", parent=None)
    audit.record(db, "workflow.create", user, target=audit.Target.of(workflow))
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
    try:
        revision = versions.save(
            db,
            workflow,
            user,
            body.name.strip(),
            body.graph.model_dump(),
            body.base_revision,
            body.message,
        )
    except versions.StaleRevision as stale:
        raise conflict(stale, "workflow.update", user, workflow, body.base_revision) from None
    audit.record(
        db,
        "workflow.update",
        user,
        target=audit.Target.of(workflow),
        details={
            "from_revision": body.base_revision,
            "revision": revision,
            "message": versions.clean_message(body.message),
        },
    )
    return WorkflowOut.of(workflow, db)


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: uuid.UUID, db: Db, user: CurrentUser) -> None:
    workflow = get_workflow(db, user, workflow_id)
    audit.record(
        db,
        "workflow.delete",
        user,
        target=audit.Target.of(workflow),
        details={"revision": workflow.revision},
    )
    db.delete(workflow)

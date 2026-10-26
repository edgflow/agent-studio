"""Version history: list, open, compare and restore revisions."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from studio import versions
from studio.auth import CurrentUser
from studio.db import Db
from studio.models import User, WorkflowRevision
from studio.routes.workflows import WorkflowOut, conflict, get_workflow

router = APIRouter(prefix="/api/workflows", tags=["versions"])


class RevisionSummary(BaseModel):
    revision: int
    parent_revision: int | None
    author: str
    message: str | None
    created_at: datetime


class RevisionOut(RevisionSummary):
    name: str
    graph: dict[str, Any]


class RestoreRequest(BaseModel):
    revision: int = Field(ge=1)
    base_revision: int = Field(ge=1)


def summary(r: WorkflowRevision, author: str) -> RevisionSummary:
    return RevisionSummary(
        revision=r.revision,
        parent_revision=r.parent_revision,
        author=author,
        message=r.message,
        created_at=r.created_at,
    )


def get_revision(db: Db, workflow_id: uuid.UUID, revision: int) -> WorkflowRevision:
    found = db.scalar(
        select(WorkflowRevision).where(
            WorkflowRevision.workflow_id == workflow_id, WorkflowRevision.revision == revision
        )
    )
    if found is None:
        raise HTTPException(404, "revision not found")
    return found


@router.get("/{workflow_id}/versions")
def list_versions(workflow_id: uuid.UUID, db: Db, user: CurrentUser) -> list[RevisionSummary]:
    get_workflow(db, user, workflow_id)
    rows = db.execute(
        select(WorkflowRevision, User.display_name)
        .join(User, User.id == WorkflowRevision.author_id)
        .where(WorkflowRevision.workflow_id == workflow_id)
        .order_by(WorkflowRevision.revision.desc())
    )
    return [summary(r, author) for r, author in rows]


@router.get("/{workflow_id}/versions/{revision}")
def read_version(workflow_id: uuid.UUID, revision: int, db: Db, user: CurrentUser) -> RevisionOut:
    get_workflow(db, user, workflow_id)
    r = get_revision(db, workflow_id, revision)
    author = db.get(User, r.author_id).display_name
    return RevisionOut(**summary(r, author).model_dump(), name=r.name, graph=r.graph)


@router.get("/{workflow_id}/compare")
def compare(
    workflow_id: uuid.UUID, base: int, head: int, db: Db, user: CurrentUser
) -> versions.GraphDiff:
    """What changed from revision `base` to revision `head`."""
    get_workflow(db, user, workflow_id)
    return versions.diff(
        get_revision(db, workflow_id, base).graph, get_revision(db, workflow_id, head).graph
    )


@router.post("/{workflow_id}/restore")
def restore(workflow_id: uuid.UUID, body: RestoreRequest, db: Db, user: CurrentUser) -> WorkflowOut:
    """Makes an old revision the latest again, as a *new* revision. History is never rewritten,
    and nothing runs: a restored workflow waits for someone to run it."""
    workflow = get_workflow(db, user, workflow_id)
    old = get_revision(db, workflow_id, body.revision)
    try:
        versions.save(
            db,
            workflow,
            user,
            old.name,
            old.graph,
            body.base_revision,
            f"Restored revision {old.revision}",
        )
    except versions.StaleRevision as stale:
        raise conflict(stale) from None
    return WorkflowOut.of(workflow, db)

"""Running workflows: start a run, follow it, cancel it."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from studio.auth import CurrentUser
from studio.db import Db, SessionLocal
from studio.engine import runner
from studio.engine.nodes import RunError
from studio.graph import Graph
from studio.models import Execution, User, WorkflowRevision
from studio.routes.workflows import get_workflow

router = APIRouter(prefix="/api", tags=["executions"])


class RunRequest(BaseModel):
    input: str = Field(default="", max_length=20_000)


class ExecutionOut(BaseModel):
    id: str
    workflow_id: str
    revision: int | None
    status: str
    input: str
    output: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, e: Execution) -> "ExecutionOut":
        return cls(
            id=str(e.id),
            workflow_id=str(e.workflow_id),
            revision=e.revision,
            status=e.status,
            input=e.input,
            output=e.output,
            error=e.error,
            created_at=e.created_at,
            finished_at=e.finished_at,
        )


def get_execution(db: Db, user: User, execution_id: uuid.UUID) -> Execution:
    execution = db.get(Execution, execution_id)
    if execution is None:
        raise HTTPException(404, "execution not found")
    get_workflow(db, user, execution.workflow_id)  # same organization check
    return execution


def run_in_background(execution_id: uuid.UUID) -> None:
    """Runs after the response is sent, with its own database session."""
    with SessionLocal() as db:
        execution = db.get(Execution, execution_id)
        if execution.status != "queued":
            return
        # Run exactly the revision the user started, even if someone saves meanwhile.
        snapshot = db.scalar(
            select(WorkflowRevision).where(
                WorkflowRevision.workflow_id == execution.workflow_id,
                WorkflowRevision.revision == execution.revision,
            )
        )
        execution.status = "running"
        db.commit()

        def cancelled() -> bool:
            db.refresh(execution, ["cancel_requested"])
            return execution.cancel_requested

        try:
            output = runner.run(Graph.model_validate(snapshot.graph), execution.input, cancelled)
            if output is None:
                execution.status = "cancelled"
            else:
                execution.status, execution.output = "succeeded", output
        except RunError as error:
            execution.status, execution.error = "failed", str(error)
        except Exception:
            execution.status, execution.error = "failed", "internal error"
        execution.finished_at = datetime.now(UTC)
        db.commit()


@router.post("/workflows/{workflow_id}/executions", status_code=202)
def start_execution(
    workflow_id: uuid.UUID,
    body: RunRequest,
    background: BackgroundTasks,
    db: Db,
    user: CurrentUser,
) -> ExecutionOut:
    workflow = get_workflow(db, user, workflow_id)
    execution = Execution(
        workflow_id=workflow.id, revision=workflow.revision, started_by=user.id, input=body.input
    )
    db.add(execution)
    db.flush()
    db.refresh(execution)
    background.add_task(run_in_background, execution.id)
    return ExecutionOut.of(execution)


@router.get("/workflows/{workflow_id}/executions")
def list_executions(workflow_id: uuid.UUID, db: Db, user: CurrentUser) -> list[ExecutionOut]:
    get_workflow(db, user, workflow_id)
    rows = db.scalars(
        select(Execution)
        .where(Execution.workflow_id == workflow_id)
        .order_by(Execution.created_at.desc())
        .limit(20)
    )
    return [ExecutionOut.of(e) for e in rows]


@router.get("/executions/{execution_id}")
def read_execution(execution_id: uuid.UUID, db: Db, user: CurrentUser) -> ExecutionOut:
    return ExecutionOut.of(get_execution(db, user, execution_id))


@router.post("/executions/{execution_id}/cancel")
def cancel_execution(execution_id: uuid.UUID, db: Db, user: CurrentUser) -> ExecutionOut:
    execution = get_execution(db, user, execution_id)
    if execution.status in ("queued", "running"):
        execution.cancel_requested = True
        if execution.status == "queued":
            execution.status, execution.finished_at = "cancelled", datetime.now(UTC)
    return ExecutionOut.of(execution)

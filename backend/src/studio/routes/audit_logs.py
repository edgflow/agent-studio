"""Reading the audit trail: search, filter, sort, page through, open one event, export.

Everything is filtered, sorted and paged in the database, and every query is
scoped to the caller's organization before any filter is applied.
"""

import csv
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import Select, func, or_, select

from studio import audit
from studio.auth import CurrentUser
from studio.db import Db
from studio.models import AuditEvent, Project, User

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])

EXPORT_LIMIT = 10_000


def org_admin(user: CurrentUser) -> User:
    if not user.is_org_admin:
        raise HTTPException(403, "only organization admins can read the audit log")
    return user


OrgAdmin = Annotated[User, Depends(org_admin)]


class AuditFilters(BaseModel):
    q: str | None = Field(default=None, max_length=100)  # actor, action or resource name
    actor_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    action: str | None = Field(default=None, max_length=64)
    outcome: Literal["success", "failure", "denied"] | None = None
    resource_type: str | None = Field(default=None, max_length=40)
    resource_id: str | None = Field(default=None, max_length=64)
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None


class AuditPage(AuditFilters):
    sort: Literal["occurred_at", "action", "actor_name", "outcome"] = "occurred_at"
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=100_000)


class AuditItem(BaseModel):
    id: str
    occurred_at: datetime
    actor_id: str | None
    actor_name: str | None
    action: str
    outcome: str
    resource_type: str | None
    resource_id: str | None
    resource_name: str | None
    project_id: str | None
    project_name: str | None  # its current name; None once the project is gone

    @classmethod
    def of(cls, e: AuditEvent, project_name: str | None) -> "AuditItem":
        return cls(
            id=str(e.id),
            occurred_at=e.occurred_at,
            actor_id=str(e.actor_id) if e.actor_id else None,
            actor_name=e.actor_name,
            action=e.action,
            outcome=e.outcome,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            resource_name=e.resource_name,
            project_id=str(e.project_id) if e.project_id else None,
            project_name=project_name,
        )


class AuditDetail(AuditItem):
    request_id: str | None
    source_ip: str | None
    metadata: dict[str, Any]


class AuditList(BaseModel):
    items: list[AuditItem]
    total: int
    limit: int
    offset: int


def _like(text: str) -> str:
    """A LIKE pattern that matches `text` literally (% and _ are not wildcards here)."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def matching(user: User, f: AuditFilters) -> Select:
    query = (
        select(AuditEvent, Project.name)
        .outerjoin(Project, Project.id == AuditEvent.project_id)
        .where(AuditEvent.org_id == user.org_id)  # the tenant boundary, always first
    )
    if f.q:
        pattern = _like(f.q.strip())
        query = query.where(
            or_(
                AuditEvent.actor_name.ilike(pattern, escape="\\"),
                AuditEvent.action.ilike(pattern, escape="\\"),
                AuditEvent.resource_name.ilike(pattern, escape="\\"),
            )
        )
    for column, value in (
        (AuditEvent.actor_id, f.actor_id),
        (AuditEvent.project_id, f.project_id),
        (AuditEvent.action, f.action),
        (AuditEvent.outcome, f.outcome),
        (AuditEvent.resource_type, f.resource_type),
        (AuditEvent.resource_id, f.resource_id),
    ):
        if value is not None:
            query = query.where(column == value)
    if f.since:
        query = query.where(AuditEvent.occurred_at >= f.since)
    if f.until:
        query = query.where(AuditEvent.occurred_at < f.until)
    return query


@router.get("")
def list_events(db: Db, user: OrgAdmin, page: Annotated[AuditPage, Query()]) -> AuditList:
    query = matching(user, page)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    column = getattr(AuditEvent, page.sort)
    direction = column.asc() if page.order == "asc" else column.desc()
    # The id breaks ties, so paging through equal timestamps never repeats or skips a row.
    tiebreak = AuditEvent.id.asc() if page.order == "asc" else AuditEvent.id.desc()
    rows = db.execute(
        query.order_by(direction.nulls_last(), tiebreak).limit(page.limit).offset(page.offset)
    )
    return AuditList(
        items=[AuditItem.of(e, project) for e, project in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# Declared before /{event_id}, which would otherwise try to read "export" as an id.
@router.get("/export")
def export_events(db: Db, user: OrgAdmin, filters: Annotated[AuditFilters, Query()]) -> Response:
    rows = db.execute(
        matching(user, filters)
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(EXPORT_LIMIT)
    ).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["occurred_at", "actor", "action", "outcome", "resource_type", "resource_name",
         "resource_id", "project", "request_id", "source_ip", "metadata"]
    )  # fmt: skip
    for e, project in rows:
        writer.writerow(
            safe_cell(value)
            for value in (
                e.occurred_at.astimezone(UTC).isoformat(),
                e.actor_name,
                e.action,
                e.outcome,
                e.resource_type,
                e.resource_name,
                e.resource_id,
                project,
                e.request_id,
                e.source_ip,
                json.dumps(e.details, sort_keys=True),
            )
        )
    # Exports leave the building, so the export itself is on the record.
    audit.record(
        db,
        "audit.export",
        user,
        details={"rows": len(rows), "filters": filters.model_dump(mode="json", exclude_none=True)},
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="audit-log-{stamp}.csv"'},
    )


def safe_cell(value: object) -> str:
    """Spreadsheets run cells that start with = + - or @ as formulas. Anyone can name a
    workflow "=HYPERLINK(...)", so such cells are prefixed with ' to stay plain text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/{event_id}")
def read_event(event_id: uuid.UUID, db: Db, user: OrgAdmin) -> AuditDetail:
    row = db.execute(
        select(AuditEvent, Project.name)
        .outerjoin(Project, Project.id == AuditEvent.project_id)
        .where(AuditEvent.id == event_id, AuditEvent.org_id == user.org_id)
    ).first()
    if row is None:
        raise HTTPException(404, "event not found")
    e, project = row
    return AuditDetail(
        **AuditItem.of(e, project).model_dump(),
        request_id=e.request_id,
        source_ip=e.source_ip,
        metadata=e.details,
    )

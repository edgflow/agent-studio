"""The audit trail: who did what, to which resource, when, and with what outcome.

Two ways to write an event:

- `record(db, ...)` adds it to the request's own transaction. Use it for changes
  that happened: the event commits together with the change, and if the change
  rolls back, the event goes with it. There is never a "success" for a save that
  did not land, and never a landed save without its event.
- `record_now(...)` commits at once, in a session of its own. Use it for attempts
  that fail: the request is about to raise, its transaction will roll back, and a
  failed sign-in or a rejected save would otherwise vanish with it.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from studio.db import SessionLocal
from studio.models import AuditEvent, Project, User, Workflow
from studio.request_id import current_request_id

Outcome = Literal["success", "failure", "denied"]

# Keys that look like they hold a secret are masked, whatever a caller passes in.
_SECRET_KEY = re.compile(
    r"passw|secret|token|authori[sz]ation|api.?key|cookie|credential|private.?key|session",
    re.IGNORECASE,
)
_MAX_TEXT = 500
_MAX_ITEMS = 50
_MAX_DEPTH = 3


def redact(value: Any, depth: int = 0) -> Any:
    """A copy that is safe to store: secret-looking keys masked, long text cut short,
    and no unbounded nesting or lists."""
    if depth > _MAX_DEPTH:
        return "[too deep]"
    if isinstance(value, dict):
        return {
            str(key)[:64]: "[redacted]" if _SECRET_KEY.search(str(key)) else redact(v, depth + 1)
            for key, v in list(value.items())[:_MAX_ITEMS]
        }
    if isinstance(value, list | tuple):
        return [redact(v, depth + 1) for v in value[:_MAX_ITEMS]]
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:_MAX_TEXT]


@dataclass(frozen=True)
class Target:
    """The resource an event is about. Its name is copied into the event, so the
    trail still reads well after the resource is renamed or deleted."""

    type: str
    id: uuid.UUID
    name: str | None = None
    project_id: uuid.UUID | None = None

    @classmethod
    def of(cls, obj: Project | Workflow | User) -> "Target":
        if isinstance(obj, Project):
            return cls("project", obj.id, obj.name, obj.id)
        if isinstance(obj, Workflow):
            return cls("workflow", obj.id, obj.name, obj.project_id)
        return cls("user", obj.id, obj.display_name)


def _event(
    action: str,
    actor: User | None,
    org_id: uuid.UUID | None,
    target: Target | None,
    outcome: Outcome,
    details: dict[str, Any] | None,
    source_ip: str | None,
) -> AuditEvent:
    return AuditEvent(
        org_id=org_id or (actor.org_id if actor else None),
        project_id=target.project_id if target else None,
        actor_id=actor.id if actor else None,
        actor_name=actor.display_name if actor else None,
        action=action,
        resource_type=target.type if target else None,
        resource_id=str(target.id) if target else None,
        resource_name=target.name[:200] if target and target.name else None,
        outcome=outcome,
        request_id=current_request_id(),
        source_ip=source_ip,
        details=redact(details or {}),
    )


def record(
    db: Session,
    action: str,
    actor: User | None,
    *,
    target: Target | None = None,
    outcome: Outcome = "success",
    details: dict[str, Any] | None = None,
    org_id: uuid.UUID | None = None,
    source_ip: str | None = None,
) -> None:
    """Adds an event to the current transaction: it commits only if the change does."""
    db.add(_event(action, actor, org_id, target, outcome, details, source_ip))


def record_now(
    action: str,
    actor: User | None,
    *,
    target: Target | None = None,
    outcome: Outcome = "failure",
    details: dict[str, Any] | None = None,
    org_id: uuid.UUID | None = None,
    source_ip: str | None = None,
) -> None:
    """Commits an event straight away, independent of the request's transaction."""
    with SessionLocal() as db:
        db.add(_event(action, actor, org_id, target, outcome, details, source_ip))
        db.commit()

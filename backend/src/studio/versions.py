"""Workflow revisions: conflict-safe saves, immutable history and diffs.

Optimistic concurrency: nobody holds a lock while editing. A save says which
revision it started from, and succeeds only if that is still the latest.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from studio.models import User, Workflow, WorkflowRevision


@dataclass
class StaleRevision(Exception):
    """Someone saved a newer revision after the caller loaded theirs."""

    current_revision: int
    updated_by: str
    updated_at: datetime


def clean_message(message: str | None) -> str | None:
    """Change descriptions are user text shown to others: one line, no control characters."""
    if message is None:
        return None
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", message).strip()
    return text[:500] or None


def save(
    db: Session,
    workflow: Workflow,
    author: User,
    name: str,
    graph: dict[str, Any],
    base_revision: int,
    message: str | None = None,
) -> int:
    """Writes a new revision, or raises StaleRevision. Returns the new revision number."""
    # One atomic statement: compare-and-swap on the revision column. If two
    # saves race, PostgreSQL makes the second wait for the first's row lock,
    # re-checks its WHERE against the committed row, and matches nothing.
    new_revision = db.scalar(
        update(Workflow)
        .where(Workflow.id == workflow.id, Workflow.revision == base_revision)
        .values(
            name=name,
            graph=graph,
            revision=Workflow.revision + 1,
            updated_by=author.id,
            updated_at=func.now(),
        )
        .returning(Workflow.revision)
    )
    if new_revision is None:
        db.refresh(workflow)
        latest_author = db.get(User, workflow.updated_by)
        raise StaleRevision(workflow.revision, latest_author.display_name, workflow.updated_at)
    record(db, workflow.id, new_revision, author, name, graph, message, parent=base_revision)
    db.refresh(workflow)
    return new_revision


def record(
    db: Session,
    workflow_id: uuid.UUID,
    revision: int,
    author: User,
    name: str,
    graph: dict[str, Any],
    message: str | None,
    parent: int | None,
) -> None:
    """Appends the snapshot, in the same transaction as the change it describes."""
    db.add(
        WorkflowRevision(
            workflow_id=workflow_id,
            revision=revision,
            parent_revision=parent,
            author_id=author.id,
            name=name,
            graph=graph,
            message=clean_message(message),
        )
    )
    db.flush()


@dataclass
class GraphDiff:
    nodes_added: list[str] = field(default_factory=list)
    nodes_removed: list[str] = field(default_factory=list)
    # node id -> {setting: [before, after]}; "position" when only moved
    nodes_changed: dict[str, dict[str, list[Any]]] = field(default_factory=dict)
    edges_added: list[str] = field(default_factory=list)
    edges_removed: list[str] = field(default_factory=list)


def diff(before: dict[str, Any], after: dict[str, Any]) -> GraphDiff:
    """What changed between two graphs: nodes by id, edges by their two endpoints."""
    old_nodes = {n["id"]: n for n in before.get("nodes", [])}
    new_nodes = {n["id"]: n for n in after.get("nodes", [])}
    result = GraphDiff(
        nodes_added=sorted(new_nodes.keys() - old_nodes.keys()),
        nodes_removed=sorted(old_nodes.keys() - new_nodes.keys()),
    )
    for node_id in sorted(old_nodes.keys() & new_nodes.keys()):
        old, new = old_nodes[node_id], new_nodes[node_id]
        changes = {
            key: [old["data"].get(key), new["data"].get(key)]
            for key in sorted(old["data"].keys() | new["data"].keys())
            if old["data"].get(key) != new["data"].get(key)
        }
        if old["type"] != new["type"]:
            changes["type"] = [old["type"], new["type"]]
        if old["position"] != new["position"]:
            changes["position"] = [old["position"], new["position"]]
        if changes:
            result.nodes_changed[node_id] = changes

    def edge_keys(graph: dict[str, Any]) -> set[str]:
        return {f"{e['source']} → {e['target']}" for e in graph.get("edges", [])}

    result.edges_added = sorted(edge_keys(after) - edge_keys(before))
    result.edges_removed = sorted(edge_keys(before) - edge_keys(after))
    return result

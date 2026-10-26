"""The workflow graph format: React Flow nodes and edges, validated on every save."""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

NodeType = Literal["input", "template", "llm", "output"]


# Credentials don't belong in a workflow: everyone in the project can read the graph,
# and every revision keeps a copy forever. They belong in a connection.
_SECRET_KEY = re.compile(
    r"passw|secret|token|api.?key|authori[sz]ation|credential|private.?key", re.IGNORECASE
)
_SECRET_VALUE = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|sk-[\w-]{20,}|xox[abpr]-[\w-]{10,}|AKIA[0-9A-Z]{16}"
)


class Position(BaseModel):
    x: float
    y: float


class Node(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: NodeType
    position: Position
    # Node settings, e.g. {"template": "Summarize: {input}"} or {"model": "gpt-5.4-mini"}.
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def no_secrets(cls, data: dict[str, Any]) -> dict[str, Any]:
        for key, value in data.items():
            if _SECRET_KEY.search(key) or (isinstance(value, str) and _SECRET_VALUE.search(value)):
                raise ValueError(
                    f"'{key}' looks like a credential. Workflows are visible to the whole "
                    "project and kept in every revision: use a connection instead"
                )
        return data


class Edge(BaseModel):
    id: str = Field(min_length=1, max_length=140)
    source: str
    target: str


class Graph(BaseModel):
    nodes: list[Node] = Field(default_factory=list, max_length=200)
    edges: list[Edge] = Field(default_factory=list, max_length=400)

    @model_validator(mode="after")
    def edges_connect_known_nodes(self) -> "Graph":
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node ids must be unique")
        known = set(ids)
        for e in self.edges:
            if e.source not in known or e.target not in known:
                raise ValueError(f"edge {e.id} connects a node that doesn't exist")
        return self

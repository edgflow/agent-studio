"""The workflow graph format: React Flow nodes and edges, validated on every save."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

NodeType = Literal["input", "template", "llm", "output"]


class Position(BaseModel):
    x: float
    y: float


class Node(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: NodeType
    position: Position
    # Node settings, e.g. {"template": "Summarize: {input}"} or {"model": "gpt-5.4-mini"}.
    data: dict[str, Any] = Field(default_factory=dict)


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

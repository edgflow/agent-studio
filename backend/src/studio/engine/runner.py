"""Turns a saved workflow graph into a LangGraph StateGraph and runs it."""

import operator
from collections.abc import Callable
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from studio.engine import nodes
from studio.engine.nodes import RunError
from studio.graph import Graph


class RunState(TypedDict):
    input: str
    # Each node adds its own output; the reducer merges them instead of overwriting.
    outputs: Annotated[dict[str, str], operator.or_]


def check_acyclic(graph: Graph) -> None:
    """Kahn's algorithm: if some node never reaches in-degree 0, there is a cycle."""
    indegree = {n.id: 0 for n in graph.nodes}
    for e in graph.edges:
        indegree[e.target] += 1
    ready = [n for n, d in indegree.items() if d == 0]
    seen = 0
    while ready:
        node = ready.pop()
        seen += 1
        for e in graph.edges:
            if e.source == node:
                indegree[e.target] -= 1
                if indegree[e.target] == 0:
                    ready.append(e.target)
    if seen != len(indegree):
        raise RunError("the workflow has a cycle")


def compile_graph(graph: Graph):
    if not any(n.type == "output" for n in graph.nodes):
        raise RunError("the workflow needs an output node")
    check_acyclic(graph)
    preds = {n.id: [e.source for e in graph.edges if e.target == n.id] for n in graph.nodes}
    builder = StateGraph(RunState)
    for node in graph.nodes:
        builder.add_node(node.id, make_step(node.id, node.type, node.data, preds[node.id]))
    for node in graph.nodes:
        if not preds[node.id]:
            builder.add_edge(START, node.id)
        elif len(preds[node.id]) == 1:
            builder.add_edge(preds[node.id][0], node.id)
        else:
            builder.add_edge(preds[node.id], node.id)  # wait for every input
        if not any(e.source == node.id for e in graph.edges):
            builder.add_edge(node.id, END)
    return builder.compile()


def make_step(
    node_id: str, node_type: str, data: dict, sources: list[str]
) -> Callable[[RunState], dict]:
    def step(state: RunState) -> dict:
        incoming = "\n".join(state["outputs"][s] for s in sources)
        if node_type == "input":
            result = state["input"]
        elif node_type == "template":
            result = nodes.run_template(str(data.get("template", "{input}")), incoming)
        elif node_type == "llm":
            result = nodes.llm_complete(incoming, data.get("model"))
        else:  # output
            result = incoming
        return {"outputs": {node_id: result}}

    return step


def run(graph: Graph, text: str, cancelled: Callable[[], bool]) -> str | None:
    """Runs to the end and returns the output, or None if cancelled between steps."""
    compiled = compile_graph(graph)
    state: dict = {"input": text, "outputs": {}}
    for update in compiled.stream(state, stream_mode="values"):
        state = update
        if cancelled():
            return None
    outputs = [state["outputs"][n.id] for n in graph.nodes if n.type == "output"]
    return "\n".join(outputs)

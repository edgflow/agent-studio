import time

import pytest

from studio.engine import nodes, runner
from studio.engine.nodes import RunError
from studio.graph import Graph


def graph(nodes_, edges):
    return Graph.model_validate(
        {
            "nodes": [
                {"id": i, "type": t, "position": {"x": 0, "y": 0}, "data": d} for i, t, d in nodes_
            ],
            "edges": [{"id": f"{s}-{t}", "source": s, "target": t} for s, t in edges],
        }
    )


def test_templates_run_in_order():
    g = graph(
        [
            ("in", "input", {}),
            ("a", "template", {"template": "<{input}>"}),
            ("b", "template", {"template": "[{input}]"}),
            ("out", "output", {}),
        ],
        [("in", "a"), ("a", "b"), ("b", "out")],
    )
    assert runner.run(g, "hi", lambda: False) == "[<hi>]"


def test_a_node_with_two_inputs_waits_for_both():
    g = graph(
        [
            ("in", "input", {}),
            ("x", "template", {"template": "x:{input}"}),
            ("y", "template", {"template": "y:{input}"}),
            ("out", "output", {}),
        ],
        [("in", "x"), ("in", "y"), ("x", "out"), ("y", "out")],
    )
    assert runner.run(g, "q", lambda: False) == "x:q\ny:q"


def test_cycles_are_rejected():
    g = graph(
        [("a", "template", {}), ("b", "template", {}), ("out", "output", {})],
        [("a", "b"), ("b", "a"), ("b", "out")],
    )
    with pytest.raises(RunError, match="cycle"):
        runner.run(g, "", lambda: False)


def test_llm_nodes_call_the_model(monkeypatch):
    monkeypatch.setattr(nodes, "llm_complete", lambda prompt, model: f"answer to {prompt}")
    g = graph(
        [("in", "input", {}), ("m", "llm", {}), ("out", "output", {})],
        [("in", "m"), ("m", "out")],
    )
    assert runner.run(g, "2+2", lambda: False) == "answer to 2+2"


def test_running_through_the_api(seeded, make_client):
    alice = make_client("alice@acme.test")
    project = next(p["id"] for p in alice.get("/api/projects").json() if p["name"] == "Support Bot")
    workflow = alice.get(f"/api/projects/{project}/workflows").json()[0]["id"]
    started = alice.post(
        f"/api/workflows/{workflow}/executions", json={"input": "My invoice is wrong"}
    )
    assert started.status_code == 202
    for _ in range(50):
        run = alice.get(f"/api/executions/{started.json()['id']}").json()
        if run["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert run["status"] == "succeeded"
    assert run["output"] == "Customer ticket:\nMy invoice is wrong\n\nRoute to: support queue"

"use client";

import "@xyflow/react/dist/style.css";

import {
  addEdge,
  Background,
  type Connection,
  Controls,
  type Edge,
  type Node,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Inspector } from "@/components/editor/Inspector";
import { RunPanel } from "@/components/editor/RunPanel";
import { NODE_STYLE, nodeTypes } from "@/components/editor/StudioNode";
import { ApiError, api } from "@/lib/api";
import type { Graph, NodeType, Workflow } from "@/lib/types";

/** React Flow keeps UI state on nodes (selected, measured…); only these fields are saved. */
function toGraph(nodes: Node[], edges: Edge[]): Graph {
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.type as NodeType,
      position: n.position,
      data: n.data as Record<string, string>,
    })),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target })),
  };
}

/** Short random ids for new nodes ("template-k3f9a"). */
function newNodeId(type: NodeType): string {
  return `${type}-${crypto.randomUUID().slice(0, 5)}`;
}

function Editor() {
  const { id } = useParams<{ id: string }>();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    api<Workflow>(`/api/workflows/${id}`).then((w) => {
      setWorkflow(w);
      setNodes(w.graph.nodes);
      setEdges(w.graph.edges);
    });
  }, [id, setNodes, setEdges]);

  const onConnect = useCallback(
    (c: Connection) => setEdges((all) => addEdge({ ...c, id: `${c.source}-${c.target}` }, all)),
    [setEdges],
  );

  function addNode(type: NodeType) {
    const nodeId = newNodeId(type);
    const data = type === "template" ? { template: "{input}" } : {};
    setNodes((all) => [...all, { id: nodeId, type, position: { x: 80 + all.length * 40, y: 260 }, data }]);
  }

  async function save() {
    if (!workflow) return;
    setStatus("Saving…");
    try {
      const saved = await api<Workflow>(`/api/workflows/${id}`, {
        method: "PUT",
        json: { name: workflow.name, graph: toGraph(nodes, edges) },
      });
      setWorkflow(saved);
      setStatus(`Saved at ${new Date(saved.updated_at).toLocaleTimeString()}`);
    } catch (e) {
      setStatus(e instanceof ApiError ? `Save failed: ${e.message}` : "Save failed");
    }
  }

  const selected = nodes.find((n) => n.selected);
  if (!workflow) return <p className="p-8 text-muted">Loading…</p>;

  return (
    <div className="flex flex-1">
      <div className="flex flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-border px-4 py-2">
          <Link href={`/projects/${workflow.project_id}`} className="text-sm text-muted hover:text-text">←</Link>
          <h1 className="font-semibold">{workflow.name}</h1>
          <span className="text-xs text-muted">last saved by {workflow.updated_by}</span>
          <div className="ml-auto flex items-center gap-2">
            {(Object.keys(NODE_STYLE) as NodeType[]).map((t) => (
              <button key={t} onClick={() => addNode(t)}
                className="rounded border border-border px-2 py-1 text-xs hover:bg-raised">
                + {NODE_STYLE[t].label}
              </button>
            ))}
            <span className="text-xs text-muted">{status}</span>
            <button onClick={save} className="rounded bg-rust px-4 py-1 text-sm font-semibold text-canvas">Save</button>
          </div>
        </div>
        <div className="flex-1">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange} onConnect={onConnect} colorMode="dark" fitView>
            <Background />
            <Controls />
          </ReactFlow>
        </div>
      </div>
      <aside className="w-80 space-y-6 border-l border-border bg-surface p-4">
        {selected ? (
          <Inspector
            node={selected}
            onChange={(data) => setNodes((all) => all.map((n) => (n.id === selected.id ? { ...n, data } : n)))}
            onDelete={() => {
              setNodes((all) => all.filter((n) => n.id !== selected.id));
              setEdges((all) => all.filter((e) => e.source !== selected.id && e.target !== selected.id));
            }}
          />
        ) : (
          <p className="text-sm text-muted">Select a node to edit its settings.</p>
        )}
        <RunPanel workflowId={workflow.id} />
      </aside>
    </div>
  );
}

export default function Page() {
  return (
    <AppShell>
      <Editor />
    </AppShell>
  );
}

"use client";

import "@xyflow/react/dist/style.css";

import {
  addEdge,
  Background,
  type Connection,
  Controls,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { type Conflict, ConflictBanner } from "@/components/editor/ConflictBanner";
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
  // The revision this editor loaded: every save says "I started from this one".
  const [baseRevision, setBaseRevision] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState<Conflict | null>(null);

  const show = useCallback(
    (w: Workflow) => {
      setWorkflow(w);
      setNodes(w.graph.nodes);
      setEdges(w.graph.edges);
      setBaseRevision(w.revision);
      setDirty(false);
      setConflict(null);
    },
    [setNodes, setEdges],
  );
  const load = useCallback(() => api<Workflow>(`/api/workflows/${id}`).then(show), [id, show]);

  useEffect(() => {
    api<Workflow>(`/api/workflows/${id}`).then(show);
  }, [id, show]);

  // Selecting or measuring a node is not an edit; moving, adding or removing one is.
  function onNodesEdit(changes: NodeChange[]) {
    onNodesChange(changes);
    if (changes.some((c) => c.type !== "select" && c.type !== "dimensions")) setDirty(true);
  }
  function onEdgesEdit(changes: EdgeChange[]) {
    onEdgesChange(changes);
    if (changes.some((c) => c.type !== "select")) setDirty(true);
  }

  const onConnect = useCallback(
    (c: Connection) => {
      setEdges((all) => addEdge({ ...c, id: `${c.source}-${c.target}` }, all));
      setDirty(true);
    },
    [setEdges],
  );

  function addNode(type: NodeType) {
    const nodeId = newNodeId(type);
    const data = type === "template" ? { template: "{input}" } : {};
    setNodes((all) => [...all, { id: nodeId, type, position: { x: 80 + all.length * 40, y: 260 }, data }]);
    setDirty(true);
  }

  async function save() {
    if (!workflow) return;
    setStatus("Saving…");
    try {
      const saved = await api<Workflow>(`/api/workflows/${id}`, {
        method: "PUT",
        json: { name: workflow.name, graph: toGraph(nodes, edges), base_revision: baseRevision },
      });
      setWorkflow(saved);
      setBaseRevision(saved.revision);
      setDirty(false);
      setStatus(`Saved revision ${saved.revision}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Someone saved first. Keep the local nodes and edges untouched.
        setConflict((e.body as { detail: Conflict }).detail);
        setStatus("Not saved");
      } else {
        setStatus(e instanceof ApiError ? `Save failed: ${e.message}` : "Save failed");
      }
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
          <span className="rounded bg-raised px-2 py-0.5 text-xs text-muted">rev {baseRevision}</span>
          <span className="text-xs text-muted">last saved by {workflow.updated_by}</span>
          {dirty && <span className="text-xs text-amber">● Unsaved changes</span>}
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
        {conflict && <ConflictBanner conflict={conflict} onReload={load} onDismiss={() => setConflict(null)} />}
        <div className="flex-1">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesEdit}
            onEdgesChange={onEdgesEdit} onConnect={onConnect} colorMode="dark" fitView>
            <Background />
            <Controls />
          </ReactFlow>
        </div>
      </div>
      <aside className="w-80 space-y-6 border-l border-border bg-surface p-4">
        {selected ? (
          <Inspector
            node={selected}
            onChange={(data) => {
              setNodes((all) => all.map((n) => (n.id === selected.id ? { ...n, data } : n)));
              setDirty(true);
            }}
            onDelete={() => {
              setNodes((all) => all.filter((n) => n.id !== selected.id));
              setEdges((all) => all.filter((e) => e.source !== selected.id && e.target !== selected.id));
              setDirty(true);
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

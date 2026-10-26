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
import { HistoryPanel } from "@/components/editor/HistoryPanel";
import { Inspector } from "@/components/editor/Inspector";
import { RunPanel } from "@/components/editor/RunPanel";
import { Presence } from "@/components/editor/Presence";
import { NODE_STYLE, nodeTypes } from "@/components/editor/StudioNode";
import { ApiError, api } from "@/lib/api";
import type { Graph, NodeType, Project, Workflow } from "@/lib/types";
import { type LiveEvent, useLive } from "@/lib/useLive";

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
  const [project, setProject] = useState<Project | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [status, setStatus] = useState("");
  // The revision this editor loaded: every save says "I started from this one".
  const [baseRevision, setBaseRevision] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [message, setMessage] = useState("");
  const [tab, setTab] = useState<"edit" | "history">("edit");
  const [compareFrom, setCompareFrom] = useState<number | null>(null);
  const [deletedBy, setDeletedBy] = useState<string | null>(null);

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
    api<Workflow>(`/api/workflows/${id}`).then((w) => {
      show(w);
      // The project says what this user's role lets them do here.
      api<Project>(`/api/projects/${w.project_id}`).then(setProject);
    });
  }, [id, show]);

  // Someone else saved or deleted this workflow. With nothing unsaved here, just move to
  // their revision; with unsaved changes, warn now instead of letting the save fail later.
  function onLive(event: LiveEvent) {
    if (event.type === "deleted") return setDeletedBy(event.by);
    if (event.revision <= baseRevision) return; // our own save, or one we already have
    if (!dirty) {
      load();
      setStatus(`Updated to ${event.by}'s revision ${event.revision}`);
    } else {
      setConflict({
        message: `${event.by} saved revision ${event.revision}`,
        current_revision: event.revision,
        updated_by: event.by,
        updated_at: new Date().toISOString(),
        early: true,
      });
    }
  }
  const live = useLive(id, dirty, onLive);

  // Until the project has loaded, offer nothing that changes the workflow.
  const can = (p: Project["permissions"][number]) => project?.permissions.includes(p) ?? false;
  const canEdit = can("edit");

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
      if (!canEdit) return;
      setEdges((all) => addEdge({ ...c, id: `${c.source}-${c.target}` }, all));
      setDirty(true);
    },
    [setEdges, canEdit],
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
        json: {
          name: workflow.name,
          graph: toGraph(nodes, edges),
          base_revision: baseRevision,
          message: message.trim() || null,
        },
      });
      setWorkflow(saved);
      setBaseRevision(saved.revision);
      setDirty(false);
      setMessage("");
      setStatus(`Saved revision ${saved.revision}`);
    } catch (e) {
      handleSaveError(e);
    }
  }

  function handleSaveError(e: unknown) {
    if (e instanceof ApiError && e.status === 409) {
      // Someone saved first. Keep the local nodes and edges untouched.
      setConflict((e.body as { detail: Conflict }).detail);
      setStatus("Not saved");
    } else {
      setStatus(e instanceof ApiError ? `Save failed: ${e.message}` : "Save failed");
    }
  }

  async function restore(revision: number) {
    if (dirty && !window.confirm("Restoring replaces your unsaved changes. Continue?")) return;
    try {
      show(await api<Workflow>(`/api/workflows/${id}/restore`, {
        method: "POST",
        json: { revision, base_revision: baseRevision },
      }));
      setStatus(`Restored rev ${revision} as a new revision`);
    } catch (e) {
      handleSaveError(e);
    }
  }

  // The newest revision on the server: ours, unless a conflict told us about a newer one.
  const latest = conflict?.current_revision ?? baseRevision;

  const selected = nodes.find((n) => n.selected);
  if (!workflow) return <p className="p-8 text-muted">Loading…</p>;

  return (
    <div className="flex flex-1">
      <div className="flex flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 whitespace-nowrap border-b border-border px-4 py-2">
          <Link href={`/projects/${workflow.project_id}`} className="text-sm text-muted hover:text-text">←</Link>
          <h1 className="font-semibold">{workflow.name}</h1>
          <span className="rounded bg-raised px-2 py-0.5 text-xs text-muted">rev {baseRevision}</span>
          <span className="text-xs text-muted">last saved by {workflow.updated_by}</span>
          {dirty && <span className="text-xs text-amber">● Unsaved changes</span>}
          <Presence people={live.people} online={live.online} />
          {project && !canEdit && (
            <span className="ml-auto rounded border border-border px-2 py-0.5 text-xs text-muted">
              View only · you are a {project.role} in this project
            </span>
          )}
          {canEdit && <div className="ml-auto flex items-center gap-2">
            {(Object.keys(NODE_STYLE) as NodeType[]).map((t) => (
              <button key={t} onClick={() => addNode(t)}
                className="rounded border border-border px-2 py-1 text-xs hover:bg-raised">
                + {NODE_STYLE[t].label}
              </button>
            ))}
            <input value={message} onChange={(e) => setMessage(e.target.value)} maxLength={500}
              placeholder="Describe your change" className="w-44 rounded bg-raised px-2 py-1 text-xs" />
            <span className="text-xs text-muted">{status}</span>
            <button onClick={save} className="rounded bg-rust px-4 py-1 text-sm font-semibold text-canvas">Save</button>
          </div>}
        </div>
        {deletedBy && (
          <div className="border-b border-danger bg-danger/10 px-4 py-2 text-sm">
            <strong>{deletedBy} deleted this workflow.</strong> Saving is no longer possible.{" "}
            <Link href={`/projects/${workflow.project_id}`} className="underline">Back to the project</Link>
          </div>
        )}
        {conflict && (
          <ConflictBanner conflict={conflict} onReload={load} onDismiss={() => setConflict(null)}>
            <button
              onClick={() => {
                setCompareFrom(baseRevision);
                setTab("history");
              }}
              className="rounded border border-amber px-3 py-1 hover:bg-amber/20">
              Compare with rev {conflict.current_revision}
            </button>
          </ConflictBanner>
        )}
        <div className="flex-1">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesEdit}
            onEdgesChange={onEdgesEdit} onConnect={onConnect} colorMode="dark" fitView
            nodesDraggable={canEdit} nodesConnectable={canEdit} deleteKeyCode={canEdit ? "Backspace" : null}>
            <Background />
            <Controls />
          </ReactFlow>
        </div>
      </div>
      <aside className="w-80 space-y-6 border-l border-border bg-surface p-4">
        <div className="flex gap-1 text-sm">
          {(["edit", "history"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`rounded px-3 py-1 capitalize ${tab === t ? "bg-raised" : "text-muted"}`}>
              {t}
            </button>
          ))}
        </div>
        {tab === "history" ? (
          <HistoryPanel workflowId={workflow.id} latest={latest} focus={compareFrom} canRestore={canEdit}
            onRestore={restore} />
        ) : selected ? (
          <Inspector
            node={selected}
            readOnly={!canEdit}
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
          <p className="text-sm text-muted">Select a node to {canEdit ? "edit" : "see"} its settings.</p>
        )}
        {tab === "edit" && can("run") && <RunPanel workflowId={workflow.id} />}
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

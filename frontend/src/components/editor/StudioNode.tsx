"use client";

import { Handle, type NodeProps, Position } from "@xyflow/react";

import type { NodeType } from "@/lib/types";

export const NODE_STYLE: Record<NodeType, { label: string; color: string }> = {
  input: { label: "Input", color: "border-teal" },
  template: { label: "Template", color: "border-amber" },
  llm: { label: "LLM", color: "border-ai" },
  output: { label: "Output", color: "border-rust" },
};

/** One box on the canvas: its type, a one-line summary of its settings, and its handles. */
export function StudioNode({ type, data, selected }: NodeProps) {
  const kind = type as NodeType;
  const settings = data as Record<string, string>;
  const summary = kind === "template" ? settings.template : kind === "llm" ? settings.model || "default model" : settings.label;
  return (
    <div className={`w-48 rounded-lg border-2 bg-surface px-3 py-2 text-sm ${NODE_STYLE[kind].color} ${selected ? "ring-2 ring-text" : ""}`}>
      {kind !== "input" && <Handle type="target" position={Position.Left} />}
      <div className="font-semibold">{NODE_STYLE[kind].label}</div>
      {summary && <div className="truncate text-xs text-muted">{summary}</div>}
      {kind !== "output" && <Handle type="source" position={Position.Right} />}
    </div>
  );
}

export const nodeTypes = { input: StudioNode, template: StudioNode, llm: StudioNode, output: StudioNode };

"use client";

import type { Node } from "@xyflow/react";

import { NODE_STYLE } from "@/components/editor/StudioNode";
import type { NodeType } from "@/lib/types";

/** Settings of the selected node. */
export function Inspector({
  node,
  onChange,
  onDelete,
}: {
  node: Node;
  onChange: (data: Record<string, string>) => void;
  onDelete: () => void;
}) {
  const kind = node.type as NodeType;
  const data = node.data as Record<string, string>;
  return (
    <div className="space-y-3">
      <h3 className="font-semibold">{NODE_STYLE[kind].label} node</h3>
      {kind === "template" && (
        <label className="block text-sm">
          Template <span className="text-muted">({"{input}"} is replaced)</span>
          <textarea className="mt-1 h-28 w-full rounded bg-raised p-2 font-mono text-xs"
            value={data.template ?? ""} onChange={(e) => onChange({ ...data, template: e.target.value })} />
        </label>
      )}
      {kind === "llm" && (
        <label className="block text-sm">
          Model
          <input className="mt-1 w-full rounded bg-raised px-2 py-1" placeholder="server default"
            value={data.model ?? ""} onChange={(e) => onChange({ ...data, model: e.target.value })} />
        </label>
      )}
      {(kind === "input" || kind === "output") && (
        <label className="block text-sm">
          Label
          <input className="mt-1 w-full rounded bg-raised px-2 py-1"
            value={data.label ?? ""} onChange={(e) => onChange({ ...data, label: e.target.value })} />
        </label>
      )}
      <button onClick={onDelete} className="text-sm text-danger hover:underline">Delete node</button>
    </div>
  );
}

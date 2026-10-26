"use client";

import { useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { Execution } from "@/lib/types";

const FINISHED = ["succeeded", "failed", "cancelled"];

/** Starts a run of the saved workflow and polls it until it finishes. */
export function RunPanel({ workflowId }: { workflowId: string }) {
  const [input, setInput] = useState("My invoice shows the wrong amount.");
  const [run, setRun] = useState<Execution | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!run || FINISHED.includes(run.status)) return;
    const timer = setTimeout(() => api<Execution>(`/api/executions/${run.id}`).then(setRun), 400);
    return () => clearTimeout(timer);
  }, [run]);

  async function start() {
    setError(null);
    try {
      setRun(await api<Execution>(`/api/workflows/${workflowId}/executions`, { method: "POST", json: { input } }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the run");
    }
  }

  async function cancel() {
    if (run) setRun(await api<Execution>(`/api/executions/${run.id}/cancel`, { method: "POST" }));
  }

  return (
    <div className="space-y-2">
      <h3 className="font-semibold">Run</h3>
      <textarea className="h-20 w-full rounded bg-raised p-2 text-sm" value={input}
        onChange={(e) => setInput(e.target.value)} />
      <div className="flex gap-2">
        <button onClick={start} className="rounded bg-ok px-3 py-1 text-sm font-semibold text-canvas">Run saved version</button>
        {run && !FINISHED.includes(run.status) && (
          <button onClick={cancel} className="rounded border border-border px-3 py-1 text-sm">Cancel</button>
        )}
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      {run && (
        <div className="rounded bg-raised p-2 text-xs">
          <div className="mb-1 font-semibold">Status: {run.status}</div>
          {run.output && <pre className="whitespace-pre-wrap">{run.output}</pre>}
          {run.error && <p className="text-danger">{run.error}</p>}
        </div>
      )}
    </div>
  );
}

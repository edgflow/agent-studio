"use client";

import { useEffect, useState } from "react";

import { DiffView, type GraphDiff, isEmpty } from "@/components/editor/DiffView";
import { api } from "@/lib/api";

type Revision = {
  revision: number;
  parent_revision: number | null;
  author: string;
  message: string | null;
  created_at: string;
};

/** Every saved revision, newest first. Pick one to see how it differs from the latest,
 *  and restore it (which saves it again as a new revision). */
export function HistoryPanel({
  workflowId,
  latest,
  focus,
  onRestore,
}: {
  workflowId: string;
  latest: number;
  focus: number | null; // a revision to compare right away (e.g. after a conflict)
  onRestore: (revision: number) => void;
}) {
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [picked, setPicked] = useState<number | null>(focus);
  const [diff, setDiff] = useState<GraphDiff | null>(null);

  useEffect(() => {
    api<Revision[]>(`/api/workflows/${workflowId}/versions`).then(setRevisions);
  }, [workflowId, latest]);

  useEffect(() => {
    if (picked === null || picked === latest) return;
    api<GraphDiff>(`/api/workflows/${workflowId}/compare?base=${picked}&head=${latest}`).then(setDiff);
  }, [workflowId, picked, latest]);

  return (
    <div className="space-y-3">
      <h3 className="font-semibold">History</h3>
      <ul className="max-h-64 space-y-1 overflow-y-auto">
        {revisions.map((r) => (
          <li key={r.revision}>
            <button onClick={() => setPicked(r.revision)}
              className={`w-full rounded px-2 py-1 text-left text-xs hover:bg-raised ${picked === r.revision ? "bg-raised" : ""}`}>
              <span className="font-semibold">rev {r.revision}</span> · {r.author} ·{" "}
              {new Date(r.created_at).toLocaleTimeString()}
              {r.revision === latest && <span className="ml-1 text-teal">latest</span>}
              {r.message && <div className="truncate text-muted">{r.message}</div>}
            </button>
          </li>
        ))}
      </ul>
      {picked !== null && picked !== latest && diff && (
        <div className="space-y-2 rounded border border-border p-2">
          <div className="text-xs text-muted">Changes from rev {picked} to rev {latest}:</div>
          <DiffView diff={diff} />
          {!isEmpty(diff) && (
            <button onClick={() => onRestore(picked)}
              className="rounded border border-teal px-2 py-1 text-xs text-teal hover:bg-teal/10">
              Restore rev {picked} as a new revision
            </button>
          )}
        </div>
      )}
    </div>
  );
}

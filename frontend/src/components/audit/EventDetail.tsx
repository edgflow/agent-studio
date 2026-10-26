"use client";

import { useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { AuditDetail, AuditOutcome } from "@/lib/types";

const OUTCOME_STYLE: Record<AuditOutcome, string> = {
  success: "border-ok/40 text-ok",
  failure: "border-danger/40 text-danger",
  denied: "border-amber/40 text-amber",
};

export function OutcomeBadge({ outcome }: { outcome: AuditOutcome }) {
  return <span className={`rounded border px-1.5 py-0.5 text-xs ${OUTCOME_STYLE[outcome]}`}>{outcome}</span>;
}

/** One event in full, with shortcuts to the events around it. */
export function EventDetail({
  eventId,
  onClose,
  onActor,
  onResource,
}: {
  eventId: string;
  onClose: () => void;
  onActor: (id: string, name: string) => void;
  onResource: (type: string, id: string, name: string) => void;
}) {
  const [result, setResult] = useState<{ id: string; event?: AuditDetail; error?: string } | null>(null);

  useEffect(() => {
    api<AuditDetail>(`/api/audit-logs/${eventId}`)
      .then((event) => setResult({ id: eventId, event }))
      .catch((e) => setResult({ id: eventId, error: e instanceof ApiError ? e.message : "failed to load" }));
  }, [eventId]);

  const event = result?.id === eventId ? result.event : undefined;
  const error = result?.id === eventId ? result.error : undefined;

  return (
    <aside className="fixed inset-y-0 right-0 z-10 w-[26rem] overflow-y-auto border-l border-border bg-surface p-5 shadow-2xl">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-semibold">Event</h2>
        <button onClick={onClose} className="text-muted hover:text-text" aria-label="Close">✕</button>
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      {!event && !error && <p className="text-sm text-muted">Loading…</p>}
      {event && (
        <div className="space-y-4 text-sm">
          <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-2">
            <dt className="text-muted">When</dt>
            <dd>
              {new Date(event.occurred_at).toLocaleString()}
              <div className="text-xs text-muted">{event.occurred_at}</div>
            </dd>
            <dt className="text-muted">Action</dt>
            <dd className="font-mono">{event.action}</dd>
            <dt className="text-muted">Outcome</dt>
            <dd><OutcomeBadge outcome={event.outcome} /></dd>
            <dt className="text-muted">Actor</dt>
            <dd>{event.actor_name ?? "unknown"}</dd>
            <dt className="text-muted">Resource</dt>
            <dd>
              {event.resource_type ? `${event.resource_type} · ${event.resource_name ?? event.resource_id}` : "—"}
            </dd>
            <dt className="text-muted">Project</dt>
            <dd>{event.project_name ?? (event.project_id ? "(deleted)" : "—")}</dd>
            <dt className="text-muted">Request id</dt>
            <dd className="break-all font-mono text-xs">{event.request_id ?? "—"}</dd>
            {event.source_ip && (
              <>
                <dt className="text-muted">IP address</dt>
                <dd className="font-mono text-xs">{event.source_ip}</dd>
              </>
            )}
            <dt className="text-muted">Event id</dt>
            <dd className="break-all font-mono text-xs">{event.id}</dd>
          </dl>
          <div>
            <div className="mb-1 text-muted">Details</div>
            <pre className="overflow-x-auto rounded bg-canvas p-3 text-xs">
              {JSON.stringify(event.metadata, null, 2)}
            </pre>
          </div>
          <div className="flex flex-col gap-2">
            {event.actor_id && (
              <button onClick={() => onActor(event.actor_id!, event.actor_name ?? "unknown")}
                className="rounded border border-border px-3 py-1.5 text-left hover:bg-raised">
                Everything {event.actor_name} did
              </button>
            )}
            {event.resource_type && event.resource_id && (
              <button
                onClick={() => onResource(event.resource_type!, event.resource_id!, event.resource_name ?? event.resource_id!)}
                className="rounded border border-border px-3 py-1.5 text-left hover:bg-raised">
                Full history of this {event.resource_type}
              </button>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}

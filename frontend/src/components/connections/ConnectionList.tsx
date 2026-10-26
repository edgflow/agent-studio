"use client";

import { useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { Connection, ProviderInfo } from "@/lib/types";

/** Sends the browser to the provider. The backend made the URL (state, PKCE challenge,
 *  fixed redirect URI); the frontend only follows it. */
async function connect(provider: string, projectId: string | null, onError: (m: string) => void) {
  try {
    const { authorize_url } = await api<{ authorize_url: string }>(`/api/connections/${provider}/start`, {
      method: "POST",
      json: { project_id: projectId },
    });
    window.location.assign(authorize_url);
  } catch (e) {
    onError(e instanceof ApiError ? e.message : "Could not start connecting");
  }
}

/** The connections of one owner (you, or one project), plus Connect buttons for the
 *  providers it doesn't have yet. */
export function ConnectionList({
  connections,
  providers,
  projectId,
  canManage,
  onChange,
}: {
  connections: Connection[];
  providers: ProviderInfo[];
  projectId: string | null;
  canManage: boolean;
  onChange: () => void;
}) {
  const [note, setNote] = useState<{ text: string; tone: "ok" | "warn" } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const fail = (text: string) => setNote({ text, tone: "warn" });

  async function test(c: Connection) {
    setBusy(c.id);
    try {
      const checked = await api<Connection>(`/api/connections/${c.id}/test`, { method: "POST" });
      setNote(
        checked.status === "active"
          ? { text: `${c.provider_label}: the token works (@${checked.account_login}).`, tone: "ok" }
          : { text: `${c.provider_label} no longer accepts this token. Reconnect to fix it.`, tone: "warn" },
      );
      onChange();
    } catch (e) {
      fail(e instanceof ApiError ? e.message : "Check failed");
    } finally {
      setBusy(null);
    }
  }

  async function disconnect(c: Connection) {
    if (!window.confirm(`Disconnect ${c.provider_label} (@${c.account_login})? Workflows using it will stop working.`)) return;
    setBusy(c.id);
    try {
      const r = await api<{ revoked_at_provider: boolean; message: string }>(`/api/connections/${c.id}`, {
        method: "DELETE",
      });
      setNote({ text: r.message, tone: r.revoked_at_provider ? "ok" : "warn" });
      onChange();
    } catch (e) {
      fail(e instanceof ApiError ? e.message : "Could not disconnect");
    } finally {
      setBusy(null);
    }
  }

  const missing = providers.filter((p) => !connections.some((c) => c.provider === p.name));

  return (
    <div className="space-y-2">
      {connections.map((c) => (
        <div key={c.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3 text-sm">
          <span className="font-semibold">{c.provider_label}</span>
          <span>@{c.account_login}</span>
          {c.scopes.map((s) => (
            <span key={s} className="rounded bg-raised px-1.5 py-0.5 font-mono text-xs text-muted">{s}</span>
          ))}
          <span className={`rounded border px-1.5 py-0.5 text-xs ${c.status === "active" ? "border-ok/40 text-ok" : "border-danger/40 text-danger"}`}>
            {c.status === "active" ? "active" : "needs reconnecting"}
          </span>
          <span className="text-xs text-muted">
            connected {new Date(c.created_at).toLocaleDateString()}
            {c.last_checked_at && ` · checked ${new Date(c.last_checked_at).toLocaleTimeString()}`}
          </span>
          {canManage && (
            <span className="ml-auto flex gap-2">
              {c.status === "invalid" && (
                <button onClick={() => connect(c.provider, projectId, fail)}
                  className="rounded bg-teal px-3 py-1 text-xs font-semibold text-canvas">Reconnect</button>
              )}
              <button disabled={busy === c.id} onClick={() => test(c)}
                className="rounded border border-border px-3 py-1 text-xs hover:bg-raised disabled:opacity-50">Test</button>
              <button disabled={busy === c.id} onClick={() => disconnect(c)}
                className="rounded border border-danger/50 px-3 py-1 text-xs text-danger hover:bg-danger/10 disabled:opacity-50">
                Disconnect
              </button>
            </span>
          )}
        </div>
      ))}
      {canManage && missing.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {missing.map((p) =>
            p.configured ? (
              <button key={p.name} onClick={() => connect(p.name, projectId, fail)}
                className="rounded border border-teal px-3 py-1.5 text-sm text-teal hover:bg-teal/10">
                Connect {p.label}
              </button>
            ) : (
              <span key={p.name} className="rounded border border-dashed border-border px-3 py-1.5 text-sm text-muted"
                title="An administrator has to add this provider's credentials to the server">
                {p.label}: not set up on this server
              </span>
            ),
          )}
        </div>
      )}
      {!canManage && connections.length === 0 && <p className="text-sm text-muted">None yet.</p>}
      {note && (
        <p className={`rounded px-3 py-2 text-sm ${note.tone === "ok" ? "bg-ok/10 text-ok" : "bg-amber/10 text-amber"}`}>
          {note.text}
        </p>
      )}
    </div>
  );
}

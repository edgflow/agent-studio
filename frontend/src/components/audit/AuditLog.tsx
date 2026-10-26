"use client";

import { useEffect, useState } from "react";

import { EventDetail, OutcomeBadge } from "@/components/audit/EventDetail";
import { ApiError, api } from "@/lib/api";
import type { AuditList, Project } from "@/lib/types";

const ACTIONS = [
  "auth.login", "auth.logout",
  "project.create", "project.delete",
  "workflow.create", "workflow.update", "workflow.restore", "workflow.delete",
  "execution.start", "execution.cancel", "execution.finish",
  "member.role_change", "member.remove", "member.leave",
  "invitation.create", "invitation.revoke", "invitation.accept",
  "connection.create", "connection.delete",
  "permission.denied", "audit.export",
];
const PAGE_SIZE = 25;

type Filters = {
  q: string;
  action: string;
  outcome: string;
  projectId: string;
  from: string; // yyyy-mm-dd, a day in the viewer's time zone
  to: string;
  actor?: { id: string; name: string };
  resource?: { type: string; id: string; name: string };
};
type SortKey = "occurred_at" | "action" | "actor_name" | "outcome";

const NO_FILTERS: Filters = { q: "", action: "", outcome: "", projectId: "", from: "", to: "" };

/** The filters as API query parameters. Days become exact instants: from the start of
 *  the "from" day up to (not including) the start of the day after "to". */
function filterParams(f: Filters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q.trim()) p.set("q", f.q.trim());
  if (f.action) p.set("action", f.action);
  if (f.outcome) p.set("outcome", f.outcome);
  if (f.projectId) p.set("project_id", f.projectId);
  if (f.from) p.set("since", new Date(`${f.from}T00:00`).toISOString());
  if (f.to) {
    const end = new Date(`${f.to}T00:00`);
    end.setDate(end.getDate() + 1);
    p.set("until", end.toISOString());
  }
  if (f.actor) p.set("actor_id", f.actor.id);
  if (f.resource) {
    p.set("resource_type", f.resource.type);
    p.set("resource_id", f.resource.id);
  }
  return p;
}

/** The audit trail as a searchable table. With `projectId`, only that project's events:
 *  the view project owners and admins get. */
export function AuditLog({ projectId }: { projectId?: string }) {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<{ by: SortKey; order: "asc" | "desc" }>({ by: "occurred_at", order: "desc" });
  const [offset, setOffset] = useState(0);
  const [refreshes, setRefreshes] = useState(0);
  const [projects, setProjects] = useState<Project[]>([]);
  const [openEvent, setOpenEvent] = useState<string | null>(null);
  const [result, setResult] = useState<{ key: string; list?: AuditList; error?: ApiError } | null>(null);

  // Every filter change starts again from the first page.
  function update(change: Partial<Filters>) {
    setFilters((f) => ({ ...f, ...change }));
    setOffset(0);
  }

  useEffect(() => {
    if (!projectId) api<Project[]>("/api/projects").then(setProjects);
  }, [projectId]);

  // Search as you type, but only once typing pauses.
  useEffect(() => {
    const timer = setTimeout(() => {
      setFilters((f) => ({ ...f, q: search }));
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const params = filterParams(projectId ? { ...filters, projectId } : filters);
  const exportUrl = `/api/audit-logs/export?${params}`;
  params.set("sort", sort.by);
  params.set("order", sort.order);
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String(offset));
  const key = `${params}#${refreshes}`;

  useEffect(() => {
    const [query] = key.split("#");
    api<AuditList>(`/api/audit-logs?${query}`)
      .then((list) => setResult({ key, list }))
      .catch((e) => setResult({ key, error: e instanceof ApiError ? e : new ApiError(0, "network error", null) }));
  }, [key]);

  const current = result?.key === key ? result : null;
  const list = current?.list ?? result?.list; // keep the old rows on screen while loading
  const error = current?.error;

  function sortBy(by: SortKey) {
    setSort((s) => ({ by, order: s.by === by && s.order === "desc" ? "asc" : "desc" }));
    setOffset(0);
  }
  const arrow = (by: SortKey) => (sort.by === by ? (sort.order === "desc" ? " ↓" : " ↑") : "");

  if (error?.status === 403) {
    return (
      <p className="text-muted">
        {projectId
          ? "Only this project's owners and admins can see its activity."
          : "Only organization admins can see the audit log."}
      </p>
    );
  }

  const anyFilter = filterParams(filters).toString() !== "";
  const input = "rounded bg-raised px-2 py-1.5 text-sm";

  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        {projectId ? (
          <span className="text-sm text-muted">Every change in this project, and every refused attempt</span>
        ) : (
          <>
            <h1 className="text-2xl font-bold">Audit log</h1>
            <span className="text-sm text-muted">Every change and sign-in in your organization</span>
          </>
        )}
        <div className="ml-auto flex gap-2">
          <button onClick={() => setRefreshes((n) => n + 1)}
            className="rounded border border-border px-3 py-1.5 text-sm hover:bg-raised">Refresh</button>
          <a href={exportUrl} download onClick={() => setTimeout(() => setRefreshes((n) => n + 1), 1000)}
            className="rounded bg-teal px-3 py-1.5 text-sm font-semibold text-canvas">Export CSV</a>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input value={search} onChange={(e) => setSearch(e.target.value)} maxLength={100}
          placeholder="Search people, actions, resources" className={`${input} w-64`} />
        <select value={filters.action} onChange={(e) => update({ action: e.target.value })} className={input}>
          <option value="">All actions</option>
          {ACTIONS.map((a) => <option key={a}>{a}</option>)}
        </select>
        <select value={filters.outcome} onChange={(e) => update({ outcome: e.target.value })} className={input}>
          <option value="">All outcomes</option>
          <option value="success">success</option>
          <option value="failure">failure</option>
          <option value="denied">denied</option>
        </select>
        {!projectId && (
          <select value={filters.projectId} onChange={(e) => update({ projectId: e.target.value })} className={input}>
            <option value="">All projects</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        )}
        <label className="text-sm text-muted">
          From <input type="date" value={filters.from} onChange={(e) => update({ from: e.target.value })} className={input} />
        </label>
        <label className="text-sm text-muted">
          to <input type="date" value={filters.to} onChange={(e) => update({ to: e.target.value })} className={input} />
        </label>
        {anyFilter && (
          <button onClick={() => { setSearch(""); update(NO_FILTERS); }}
            className="text-sm text-muted hover:text-text">Clear filters</button>
        )}
      </div>

      {(filters.actor || filters.resource) && (
        <div className="mb-3 flex gap-2 text-sm">
          {filters.actor && (
            <button onClick={() => update({ actor: undefined })} className="rounded-full bg-raised px-3 py-1">
              By {filters.actor.name} ✕
            </button>
          )}
          {filters.resource && (
            <button onClick={() => update({ resource: undefined })} className="rounded-full bg-raised px-3 py-1">
              {filters.resource.type} “{filters.resource.name}” ✕
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="mb-3 rounded border border-danger/40 bg-danger/10 px-4 py-2 text-sm">
          Couldn’t load the audit log: {error.message}.{" "}
          <button onClick={() => setRefreshes((n) => n + 1)} className="underline">Try again</button>
        </div>
      )}

      <div className={`overflow-hidden rounded-lg border border-border ${current ? "" : "opacity-60"}`}>
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted">
            <tr>
              <th className="px-3 py-2"><button onClick={() => sortBy("occurred_at")}>Time{arrow("occurred_at")}</button></th>
              <th className="px-3 py-2"><button onClick={() => sortBy("actor_name")}>Actor{arrow("actor_name")}</button></th>
              <th className="px-3 py-2"><button onClick={() => sortBy("action")}>Action{arrow("action")}</button></th>
              <th className="px-3 py-2">Resource</th>
              <th className="px-3 py-2">Project</th>
              <th className="px-3 py-2"><button onClick={() => sortBy("outcome")}>Outcome{arrow("outcome")}</button></th>
            </tr>
          </thead>
          <tbody>
            {list?.items.map((e) => (
              <tr key={e.id} onClick={() => setOpenEvent(e.id)}
                className={`cursor-pointer border-t border-border hover:bg-raised ${openEvent === e.id ? "bg-raised" : ""}`}>
                <td className="whitespace-nowrap px-3 py-2" title={e.occurred_at}>
                  {new Date(e.occurred_at).toLocaleString()}
                </td>
                <td className="px-3 py-2">{e.actor_name ?? <span className="text-muted">unknown</span>}</td>
                <td className="px-3 py-2 font-mono text-xs">{e.action}</td>
                <td className="px-3 py-2">
                  {e.resource_type && <span className="text-muted">{e.resource_type} · </span>}
                  {e.resource_name}
                </td>
                <td className="px-3 py-2 text-muted">{e.project_name ?? ""}</td>
                <td className="px-3 py-2"><OutcomeBadge outcome={e.outcome} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {list && list.items.length === 0 && (
          <p className="px-3 py-8 text-center text-sm text-muted">No events match these filters.</p>
        )}
        {!list && !error && <p className="px-3 py-8 text-center text-sm text-muted">Loading…</p>}
      </div>

      {list && list.total > 0 && (
        <div className="mt-3 flex items-center justify-end gap-3 text-sm text-muted">
          <span>
            {list.offset + 1}–{list.offset + list.items.length} of {list.total}
          </span>
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="rounded border border-border px-3 py-1 enabled:hover:bg-raised disabled:opacity-40">Previous</button>
          <button disabled={offset + PAGE_SIZE >= list.total} onClick={() => setOffset(offset + PAGE_SIZE)}
            className="rounded border border-border px-3 py-1 enabled:hover:bg-raised disabled:opacity-40">Next</button>
        </div>
      )}

      {openEvent && (
        <EventDetail
          eventId={openEvent}
          onClose={() => setOpenEvent(null)}
          onActor={(id, name) => update({ actor: { id, name } })}
          onResource={(type, id, name) => update({ resource: { type, id, name } })}
        />
      )}
    </div>
  );
}

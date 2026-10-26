"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useUser } from "@/components/AppShell";
import { ApiError, api } from "@/lib/api";
import type { Invitation, Member, Project, Role } from "@/lib/types";

const ROLES: Role[] = ["owner", "admin", "editor", "viewer"];

/** The roles `me` may give `member`. Mirrors the backend rule (which has the final say):
 *  admins manage admins, editors and viewers; only owners give or take ownership. */
function choices(me: Role, member: Role): Role[] {
  if (me === "owner") return ROLES;
  if (me === "admin" && member !== "owner") return ["admin", "editor", "viewer"];
  return [];
}

export function Members({ project }: { project: Project }) {
  const router = useRouter();
  const me = useUser();
  const canManage = project.permissions.includes("manage_members");
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("editor");
  const [created, setCreated] = useState<{ email: string; link: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    api<Member[]>(`/api/projects/${project.id}/members`).then(setMembers);
    if (canManage) api<Invitation[]>(`/api/projects/${project.id}/invitations`).then(setInvitations);
  }, [project.id, canManage, reloads]);

  async function attempt(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      setReloads((n) => n + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    }
  }

  const changeRole = (m: Member, to: Role) =>
    attempt(() => api(`/api/projects/${project.id}/members/${m.user_id}`, { method: "PATCH", json: { role: to } }));

  function remove(m: Member) {
    const leaving = m.user_id === me?.id;
    if (!window.confirm(leaving ? `Leave ${project.name}?` : `Remove ${m.display_name} from ${project.name}?`)) return;
    attempt(async () => {
      await api(`/api/projects/${project.id}/members/${m.user_id}`, { method: "DELETE" });
      if (leaving) router.replace("/");
    });
  }

  function invite(event: React.FormEvent) {
    event.preventDefault();
    attempt(async () => {
      const r = await api<Invitation & { link: string }>(`/api/projects/${project.id}/invitations`, {
        method: "POST",
        json: { email, role },
      });
      setCreated({ email: r.email, link: r.link });
      setEmail("");
    });
  }

  const revoke = (i: Invitation) =>
    attempt(() => api(`/api/projects/${project.id}/invitations/${i.id}`, { method: "DELETE" }));

  return (
    <div className="space-y-6">
      {error && <p className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm">{error}</p>}

      <ul className="divide-y divide-border rounded-lg border border-border">
        {members.map((m) => {
          const options = canManage ? choices(project.role, m.role) : [];
          const isMe = m.user_id === me?.id;
          return (
            <li key={m.user_id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-raised text-xs font-semibold">
                {m.display_name.slice(0, 1)}
              </span>
              <span className="font-medium">{m.display_name}{isMe && <span className="text-muted"> (you)</span>}</span>
              {m.email && <span className="text-muted">{m.email}</span>}
              <span className="ml-auto" />
              {options.length > 0 ? (
                <select value={m.role} onChange={(e) => changeRole(m, e.target.value as Role)}
                  className="rounded bg-raised px-2 py-1" aria-label={`Role of ${m.display_name}`}>
                  {options.map((r) => <option key={r}>{r}</option>)}
                </select>
              ) : (
                <span className="text-muted">{m.role}</span>
              )}
              {(isMe || options.length > 0) && (
                <button onClick={() => remove(m)} className="text-xs text-danger hover:underline">
                  {isMe ? "Leave" : "Remove"}
                </button>
              )}
            </li>
          );
        })}
      </ul>

      {canManage && (
        <section className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted">Invite someone</h3>
          <form onSubmit={invite} className="flex gap-2">
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="name@company.com" className="flex-1 rounded bg-raised px-3 py-2 text-sm" />
            <select value={role} onChange={(e) => setRole(e.target.value as Role)} className="rounded bg-raised px-2 text-sm">
              <option value="viewer">viewer</option>
              <option value="editor">editor</option>
              <option value="admin">admin</option>
            </select>
            <button className="rounded bg-teal px-4 text-sm font-semibold text-canvas">Create link</button>
          </form>
          {created && (
            <div className="space-y-2 rounded border border-teal/40 bg-teal/10 p-3 text-sm">
              <p>
                Send this link to <strong>{created.email}</strong>. It works once, only for that address, for 7
                days. It won&apos;t be shown again.
              </p>
              <div className="flex gap-2">
                <input readOnly value={created.link} className="flex-1 rounded bg-canvas px-2 py-1 font-mono text-xs" />
                <button onClick={() => navigator.clipboard.writeText(created.link)}
                  className="rounded border border-teal px-3 text-xs text-teal">Copy</button>
              </div>
            </div>
          )}
          {invitations.length > 0 && (
            <ul className="space-y-1 text-sm">
              {invitations.map((i) => (
                <li key={i.id} className="flex items-center gap-3 text-muted">
                  <span className="text-text">{i.email}</span> {i.role} · expires{" "}
                  {new Date(i.expires_at).toLocaleDateString()}
                  <button onClick={() => revoke(i)} className="ml-auto text-xs text-danger hover:underline">Revoke</button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

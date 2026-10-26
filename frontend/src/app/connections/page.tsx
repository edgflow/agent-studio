"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { ConnectionList } from "@/components/connections/ConnectionList";
import { api } from "@/lib/api";
import type { Connection, Project, ProviderInfo } from "@/lib/types";

// The callback only ever sends these codes, never the provider's own wording.
const ERRORS: Record<string, string> = {
  cancelled: "You cancelled at the provider. Nothing was connected.",
  expired: "That took longer than ten minutes. Nothing was connected; please try again.",
  invalid_state:
    "That sign-in wasn't started from your session here, or was already used. Nothing was connected.",
  provider_error: "The provider didn't accept the request. Nothing was connected.",
  missing_scopes: "The provider granted less access than needed. Nothing was connected.",
  not_allowed: "You're no longer allowed to add connections to that project.",
  signed_out: "You were signed out on the way back. Sign in and connect again.",
};

/** The result of a round trip to a provider, from the URL the callback redirected to. */
function Outcome({ providers }: { providers: ProviderInfo[] }) {
  const router = useRouter();
  const params = useSearchParams();
  const connected = params.get("connected");
  const error = params.get("error");
  if (!connected && !error) return null;
  const label = providers.find((p) => p.name === connected)?.label ?? connected;
  return (
    <div className={`mb-6 flex items-center rounded-lg px-4 py-3 text-sm ${connected ? "bg-ok/10 text-ok" : "bg-amber/10 text-amber"}`}>
      {connected ? `Connected to ${label}. The provider confirmed the account.` : (ERRORS[error!] ?? "Nothing was connected.")}
      <button onClick={() => router.replace("/connections")} className="ml-auto" aria-label="Dismiss">✕</button>
    </div>
  );
}

function Connections() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [personal, setPersonal] = useState<Connection[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [shared, setShared] = useState<Record<string, Connection[]>>({});
  const [reloads, setReloads] = useState(0);
  const reload = () => setReloads((n) => n + 1);

  useEffect(() => {
    api<ProviderInfo[]>("/api/connections/providers").then(setProviders);
    api<Connection[]>("/api/connections").then(setPersonal);
    api<Project[]>("/api/projects").then(async (list) => {
      setProjects(list);
      const each = await Promise.all(list.map((p) => api<Connection[]>(`/api/projects/${p.id}/connections`)));
      setShared(Object.fromEntries(list.map((p, i) => [p.id, each[i]])));
    });
  }, [reloads]);

  return (
    <div className="mx-auto w-full max-w-3xl p-8">
      <h1 className="mb-2 text-2xl font-bold">Connections</h1>
      <p className="mb-6 text-sm text-muted">
        Accounts your workflows may act as. Tokens are stored encrypted and never shown, not even to you.
      </p>
      <Suspense>
        <Outcome providers={providers} />
      </Suspense>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-muted">Yours</h2>
      <p className="mb-3 text-xs text-muted">Only you can see and use these.</p>
      <ConnectionList connections={personal} providers={providers} projectId={null} canManage onChange={reload} />

      <h2 className="mb-2 mt-10 text-sm font-semibold uppercase tracking-wider text-muted">Shared with a project</h2>
      <p className="mb-3 text-xs text-muted">Every member of the project can see these; its owners and admins manage them.</p>
      <div className="space-y-6">
        {projects.map((p) => (
          <section key={p.id}>
            <h3 className="mb-2 font-semibold">{p.name} <span className="text-xs font-normal text-muted">you are {p.role}</span></h3>
            <ConnectionList connections={shared[p.id] ?? []} providers={providers} projectId={p.id}
              canManage={p.permissions.includes("manage_connections")} onChange={reload} />
          </section>
        ))}
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <AppShell>
      <Connections />
    </AppShell>
  );
}

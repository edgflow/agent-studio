"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import type { Project, WorkflowSummary } from "@/lib/types";

function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [name, setName] = useState("");

  useEffect(() => {
    api<Project>(`/api/projects/${id}`).then(setProject);
    api<WorkflowSummary[]>(`/api/projects/${id}/workflows`).then(setWorkflows);
  }, [id]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    const workflow = await api<WorkflowSummary>(`/api/projects/${id}/workflows`, {
      method: "POST",
      json: { name },
    });
    setWorkflows((all) => [...all, workflow]);
    setName("");
  }

  return (
    <div className="mx-auto w-full max-w-3xl p-8">
      <Link href="/" className="text-sm text-muted hover:text-text">← Projects</Link>
      <h1 className="mb-6 mt-2 text-2xl font-bold">{project?.name}</h1>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-muted">Workflows</h2>
      <ul className="space-y-2">
        {workflows.map((w) => (
          <li key={w.id}>
            <Link href={`/workflows/${w.id}`}
              className="flex justify-between rounded-lg border border-border bg-surface px-4 py-3 hover:border-teal">
              <span>{w.name}</span>
              <span className="text-sm text-muted">{new Date(w.updated_at).toLocaleString()}</span>
            </Link>
          </li>
        ))}
      </ul>
      <form onSubmit={create} className="mt-6 flex gap-2">
        <input className="flex-1 rounded bg-raised px-3 py-2" placeholder="New workflow name"
          value={name} onChange={(e) => setName(e.target.value)} />
        <button className="rounded bg-teal px-4 font-semibold text-canvas">Create</button>
      </form>
    </div>
  );
}

export default function Page() {
  return (
    <AppShell>
      <ProjectPage />
    </AppShell>
  );
}

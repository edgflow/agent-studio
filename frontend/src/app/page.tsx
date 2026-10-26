"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

function Projects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");

  useEffect(() => {
    api<Project[]>("/api/projects").then(setProjects);
  }, []);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    const project = await api<Project>("/api/projects", { method: "POST", json: { name } });
    setProjects((all) => [...all, project]);
    setName("");
  }

  return (
    <div className="mx-auto w-full max-w-3xl p-8">
      <h1 className="mb-6 text-2xl font-bold">Projects</h1>
      <ul className="space-y-2">
        {projects.map((p) => (
          <li key={p.id}>
            <Link href={`/projects/${p.id}`}
              className="block rounded-lg border border-border bg-surface px-4 py-3 hover:border-teal">
              {p.name}
            </Link>
          </li>
        ))}
      </ul>
      <form onSubmit={create} className="mt-6 flex gap-2">
        <input className="flex-1 rounded bg-raised px-3 py-2" placeholder="New project name"
          value={name} onChange={(e) => setName(e.target.value)} />
        <button className="rounded bg-teal px-4 font-semibold text-canvas">Create</button>
      </form>
    </div>
  );
}

export default function Home() {
  return (
    <AppShell>
      <Projects />
    </AppShell>
  );
}

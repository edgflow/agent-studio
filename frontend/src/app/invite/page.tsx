"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { ApiError, api } from "@/lib/api";
import type { Project } from "@/lib/types";

const KEY = "studio-invite-token";

function Accept() {
  const [joined, setJoined] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function accept() {
    setError(null);
    const token = sessionStorage.getItem(KEY);
    if (!token) return setError("This page needs the full invitation link. Open it again from the message you got.");
    try {
      setJoined(await api<Project>("/api/invitations/accept", { method: "POST", json: { token } }));
      sessionStorage.removeItem(KEY);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not accept the invitation");
    }
  }

  return (
    <div className="mx-auto w-full max-w-md space-y-4 p-8">
      <h1 className="text-2xl font-bold">Project invitation</h1>
      {joined ? (
        <p>
          You joined <strong>{joined.name}</strong> as {joined.role}.{" "}
          <Link href={`/projects/${joined.id}`} className="text-teal underline">Open the project</Link>
        </p>
      ) : (
        <>
          <p className="text-muted">You were invited to join a project. Accepting adds it to your projects.</p>
          <button onClick={accept} className="rounded bg-teal px-4 py-2 font-semibold text-canvas">Accept invitation</button>
        </>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
    </div>
  );
}

export default function Page() {
  // The token arrives in the #fragment, which browsers never send to a server. Keep it in
  // this tab's storage (it survives a detour through the sign-in page) and take it out of
  // the address bar, so it doesn't linger in history or get copied along with the URL.
  useEffect(() => {
    const token = window.location.hash.slice(1);
    if (token) {
      sessionStorage.setItem(KEY, token);
      window.history.replaceState(null, "", "/invite");
    }
  }, []);

  return (
    <AppShell>
      <Accept />
    </AppShell>
  );
}

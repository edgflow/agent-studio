"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("alice@acme.test");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/api/auth/login", { method: "POST", json: { email, password } });
      router.replace("/");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not sign in");
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center">
      <form onSubmit={submit} className="w-80 space-y-4 rounded-xl border border-border bg-surface p-6">
        <h1 className="text-xl font-bold">
          <span className="text-rust">Agent</span> Studio
        </h1>
        <label className="block text-sm">
          Email
          <input className="mt-1 w-full rounded bg-raised px-3 py-2" value={email}
            onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
        </label>
        <label className="block text-sm">
          Password
          <input className="mt-1 w-full rounded bg-raised px-3 py-2" type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {error && <p className="text-sm text-danger">{error}</p>}
        <button className="w-full rounded bg-rust py-2 font-semibold text-canvas">Sign in</button>
        <p className="text-xs text-muted">Demo users: alice, bob, carol @acme.test · dave@globex.test</p>
      </form>
    </div>
  );
}

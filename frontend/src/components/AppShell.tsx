"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { User } from "@/lib/types";

const UserContext = createContext<User | null>(null);
export const useUser = () => useContext(UserContext);

/** Loads the signed-in user (or sends the browser to /login) and draws the header. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api<User>("/api/auth/me")
      .then(setUser)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
      });
  }, [router]);

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  }

  if (!user) return <p className="p-8 text-muted">Loading…</p>;
  return (
    <UserContext.Provider value={user}>
      <header className="flex items-center justify-between border-b border-border bg-surface px-6 py-3">
        <Link href="/" className="text-lg font-bold">
          <span className="text-rust">Agent</span> Studio
        </Link>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-muted">{user.display_name}</span>
          <button onClick={logout} className="rounded border border-border px-3 py-1 hover:bg-raised">
            Sign out
          </button>
        </div>
      </header>
      <main className="flex flex-1 flex-col">{children}</main>
    </UserContext.Provider>
  );
}

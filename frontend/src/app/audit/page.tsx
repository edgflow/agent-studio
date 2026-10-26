"use client";

import { AppShell } from "@/components/AppShell";
import { AuditLog } from "@/components/audit/AuditLog";

export default function Page() {
  return (
    <AppShell>
      <div className="mx-auto w-full max-w-6xl p-8">
        <AuditLog />
      </div>
    </AppShell>
  );
}

"use client";

import type { Person } from "@/lib/useLive";

/** Who else has this workflow open. A ring and a pencil mark people with unsaved changes. */
export function Presence({ people, online }: { people: Person[]; online: boolean }) {
  const others = people.filter((p) => !p.you);
  const editing = others.filter((p) => p.editing);
  if (!online) return <span className="text-xs text-muted" title="Reconnecting to the live channel">○ offline</span>;
  return (
    <div className="flex items-center gap-2">
      <div className="flex -space-x-1.5">
        {others.map((p) => (
          <span key={p.name} title={`${p.name}${p.editing ? " · has unsaved changes" : " · viewing"}`}
            className={`relative flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold text-white ring-2 ${p.editing ? "ring-amber" : "ring-surface"}`}
            style={{ background: `hsl(${p.hue} 55% 42%)` }}>
            {p.initials}
            {p.editing && <span className="absolute -bottom-1 -right-1 text-[10px]">✎</span>}
          </span>
        ))}
      </div>
      {editing.length > 0 ? (
        <span className="text-xs text-amber">
          {editing.map((p) => p.name).join(", ")} {editing.length === 1 ? "is" : "are"} editing
        </span>
      ) : (
        others.length > 0 && <span className="text-xs text-muted">{others.length} viewing</span>
      )}
    </div>
  );
}

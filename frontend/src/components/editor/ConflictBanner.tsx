"use client";

export type Conflict = {
  message: string;
  current_revision: number;
  updated_by: string;
  updated_at: string;
};

/** Shown when a save was rejected because someone saved a newer revision first.
 *  The editor keeps the user's unsaved changes until they choose what to do. */
export function ConflictBanner({
  conflict,
  onReload,
  onDismiss,
  children,
}: {
  conflict: Conflict;
  onReload: () => void;
  onDismiss: () => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-amber bg-amber/10 px-4 py-2 text-sm">
      <span>
        <strong>Not saved.</strong> {conflict.updated_by} saved revision {conflict.current_revision} at{" "}
        {new Date(conflict.updated_at).toLocaleTimeString()} while you were editing. Your changes are
        still here.
      </span>
      <div className="ml-auto flex gap-2">
        {children}
        <button onClick={onReload} className="rounded border border-amber px-3 py-1 hover:bg-amber/20">
          Load revision {conflict.current_revision} (discard mine)
        </button>
        <button onClick={onDismiss} className="rounded px-3 py-1 text-muted hover:text-text">
          Keep editing
        </button>
      </div>
    </div>
  );
}

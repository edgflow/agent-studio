"use client";

export type GraphDiff = {
  nodes_added: string[];
  nodes_removed: string[];
  nodes_changed: Record<string, Record<string, [unknown, unknown]>>;
  edges_added: string[];
  edges_removed: string[];
};

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function isEmpty(diff: GraphDiff): boolean {
  return (
    !diff.nodes_added.length && !diff.nodes_removed.length && !Object.keys(diff.nodes_changed).length &&
    !diff.edges_added.length && !diff.edges_removed.length
  );
}

/** Node and connection changes between two revisions, readable at a glance. */
export function DiffView({ diff }: { diff: GraphDiff }) {
  const changed = Object.entries(diff.nodes_changed);
  if (isEmpty(diff)) return <p className="text-xs text-muted">No differences.</p>;
  return (
    <ul className="space-y-1 text-xs">
      {diff.nodes_added.map((id) => <li key={`+${id}`} className="text-ok">+ node {id}</li>)}
      {diff.nodes_removed.map((id) => <li key={`-${id}`} className="text-danger">− node {id}</li>)}
      {changed.map(([id, fields]) => (
        <li key={`~${id}`}>
          <span className="text-amber">~ node {id}</span>
          {Object.entries(fields).map(([field, [before, after]]) =>
            field === "position" ? (
              <div key={field} className="ml-3 text-muted">moved</div>
            ) : (
              <div key={field} className="ml-3">
                <span className="text-muted">{field}:</span>{" "}
                <span className="text-danger line-through">{show(before)}</span> →{" "}
                <span className="text-ok">{show(after)}</span>
              </div>
            ),
          )}
        </li>
      ))}
      {diff.edges_added.map((e) => <li key={`+${e}`} className="text-ok">+ connection {e}</li>)}
      {diff.edges_removed.map((e) => <li key={`-${e}`} className="text-danger">− connection {e}</li>)}
    </ul>
  );
}

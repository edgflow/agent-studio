// The shapes the API returns.

export type User = { id: string; email: string; display_name: string; is_org_admin: boolean };
export type Project = { id: string; name: string };
export type WorkflowSummary = { id: string; name: string; updated_at: string };

export type NodeType = "input" | "template" | "llm" | "output";
export type GraphNode = {
  id: string;
  type: NodeType;
  position: { x: number; y: number };
  data: Record<string, string>;
};
export type GraphEdge = { id: string; source: string; target: string };
export type Graph = { nodes: GraphNode[]; edges: GraphEdge[] };

export type Workflow = {
  id: string;
  project_id: string;
  name: string;
  graph: Graph;
  updated_at: string;
  updated_by: string;
};

export type Execution = {
  id: string;
  workflow_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  input: string;
  output: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

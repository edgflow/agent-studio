// The shapes the API returns.

export type User = { id: string; email: string; display_name: string; is_org_admin: boolean };
export type Role = "owner" | "admin" | "editor" | "viewer";
export type Permission =
  | "view" | "edit" | "run" | "delete_workflow" | "manage_members" | "view_audit" | "delete_project";
// `permissions` tells the UI what to offer. The API checks every request regardless.
export type Project = { id: string; name: string; role: Role; permissions: Permission[] };
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
  revision: number;
  updated_at: string;
  updated_by: string;
};

export type Execution = {
  id: string;
  workflow_id: string;
  revision: number | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  input: string;
  output: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

export type AuditOutcome = "success" | "failure" | "denied";
export type AuditItem = {
  id: string;
  occurred_at: string;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  outcome: AuditOutcome;
  resource_type: string | null;
  resource_id: string | null;
  resource_name: string | null;
  project_id: string | null;
  project_name: string | null;
};
export type AuditDetail = AuditItem & {
  request_id: string | null;
  source_ip: string | null;
  metadata: Record<string, unknown>;
};
export type AuditList = { items: AuditItem[]; total: number; limit: number; offset: number };

export type Member = {
  user_id: string;
  display_name: string;
  email: string | null; // only for people who manage members
  role: Role;
  added_at: string;
};
export type Invitation = { id: string; email: string; role: Role; created_at: string; expires_at: string };

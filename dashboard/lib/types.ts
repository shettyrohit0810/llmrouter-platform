export type Org = { id: string; name: string; slug: string; plan: string; created_at: string };
export type Project = { id: string; organization_id: string; name: string; slug: string; created_at: string };
export type Member = { user_id: string; email: string; role: Role; created_at: string };
export type Role = "owner" | "admin" | "developer" | "viewer";
export type ApiKey = {
  id: string; name: string; key_prefix: string; project_id: string | null; revoked: boolean;
  last_used_at: string | null; expires_at: string | null; created_at: string;
};
export type CreatedApiKey = { id: string; name: string; key_prefix: string; api_key: string; created_at: string };
export type UsageSummary = {
  total_requests: number; total_tokens_input: number; total_tokens_output: number;
  average_latency_ms: number; total_cost_estimate: number;
  requests_by_endpoint: Record<string, number>;
  requests_by_router: Record<string, number>;
  requests_by_model: Record<string, number>;
};
export type UsageRecord = {
  id: string; endpoint: string; router_name: string | null; model_name: string | null;
  latency_ms: number; status_code: number; created_at: string;
};
export type Experiment = {
  id: string; job_id: string | null; experiment_type: string; router_name: string | null;
  router_version: string | null; metrics: Record<string, unknown> | null;
  duration_seconds: number | null; created_at: string;
};
export type RegistryRouter = { id: string; name: string; class_name: string; trainable: boolean; status: string };
export type RouterVersion = {
  id: string; version_label: string; checkpoint_path: string; status: string;
  training_job_id: string | null; created_at: string;
};
export type AuditLog = {
  id: string; action: string; user_id: string | null; resource_type: string | null;
  resource_id: string | null; ip_address: string | null; metadata: Record<string, unknown> | null;
  created_at: string;
};

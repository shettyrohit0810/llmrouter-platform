"use client";

import { useParams } from "next/navigation";
import Shell from "@/components/Shell";
import { useLoad } from "@/components/useLoad";
import { api } from "@/lib/api";
import type { Experiment, UsageRecord, UsageSummary } from "@/lib/types";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const summary = useLoad(() => api<UsageSummary>(`/projects/${id}/usage/summary`), [id]);
  const records = useLoad(() => api<{ records: UsageRecord[] }>(`/projects/${id}/usage?limit=15`), [id]);
  const experiments = useLoad(() => api<{ experiments: Experiment[] }>(`/projects/${id}/experiments`), [id]);
  const s = summary.data;

  return (
    <Shell>
      <h1>Project usage</h1>
      {summary.error && <p className="error">{summary.error}</p>}
      {s && (
        <div className="grid">
          <Stat label="Requests" value={s.total_requests.toLocaleString()} />
          <Stat label="Avg latency" value={`${s.average_latency_ms.toFixed(0)} ms`} />
          <Stat label="Tokens out" value={s.total_tokens_output.toLocaleString()} />
          <Stat label="Est. cost" value={s.total_cost_estimate ? `$${s.total_cost_estimate.toFixed(4)}` : "n/a"} />
        </div>
      )}
      {s && (
        <div className="grid" style={{ marginTop: 16 }}>
          <Breakdown title="By endpoint" data={s.requests_by_endpoint} />
          <Breakdown title="By router" data={s.requests_by_router} />
          <Breakdown title="By model" data={s.requests_by_model} />
        </div>
      )}

      <h2>Recent requests</h2>
      {records.error && <p className="error">{records.error}</p>}
      <div className="panel">
        <table>
          <thead><tr><th>When</th><th>Endpoint</th><th>Router</th><th>Model</th><th>Latency</th><th>Status</th></tr></thead>
          <tbody>
            {records.data?.records.map((r) => (
              <tr key={r.id}>
                <td className="muted">{new Date(r.created_at).toLocaleString()}</td>
                <td><code>{r.endpoint}</code></td>
                <td>{r.router_name ?? "—"}</td>
                <td>{r.model_name ?? "—"}</td>
                <td>{r.latency_ms.toFixed(0)} ms</td>
                <td>{r.status_code}</td>
              </tr>
            ))}
            {records.data?.records.length === 0 && <tr><td colSpan={6} className="muted">No usage recorded yet. Calls made with a project-scoped API key appear here.</td></tr>}
          </tbody>
        </table>
      </div>

      <h2>Experiments</h2>
      {experiments.error && <p className="error">{experiments.error}</p>}
      <div className="panel">
        <table>
          <thead><tr><th>When</th><th>Type</th><th>Router</th><th>Duration</th><th>Metrics</th></tr></thead>
          <tbody>
            {experiments.data?.experiments.map((x) => (
              <tr key={x.id}>
                <td className="muted">{new Date(x.created_at).toLocaleString()}</td>
                <td><span className="tag">{x.experiment_type}</span></td>
                <td>{x.router_name ?? "—"}</td>
                <td>{x.duration_seconds != null ? `${x.duration_seconds.toFixed(1)} s` : "—"}</td>
                <td><code>{x.metrics ? JSON.stringify(x.metrics) : "—"}</code></td>
              </tr>
            ))}
            {experiments.data?.experiments.length === 0 && <tr><td colSpan={5} className="muted">No experiments yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </Shell>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel stat">
      <div className="v">{value}</div>
      <div className="l">{label}</div>
    </div>
  );
}

function Breakdown({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <div className="panel">
      <div className="muted" style={{ marginBottom: 6 }}>{title}</div>
      {entries.length === 0 && <div className="muted">—</div>}
      {entries.map(([k, v]) => (
        <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
          <code>{k}</code><span>{v}</span>
        </div>
      ))}
    </div>
  );
}

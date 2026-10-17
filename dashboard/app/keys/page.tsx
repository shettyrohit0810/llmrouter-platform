"use client";

import { useState } from "react";
import Shell from "@/components/Shell";
import { useLoad } from "@/components/useLoad";
import { api, ApiError } from "@/lib/api";
import type { ApiKey, CreatedApiKey, Org, Project } from "@/lib/types";

export default function KeysPage() {
  const keys = useLoad(() => api<{ api_keys: ApiKey[] }>("/api-keys"));
  const projects = useLoad(async () => {
    const { organizations } = await api<{ organizations: Org[] }>("/orgs");
    const lists = await Promise.all(
      organizations.map(async (o) => (await api<{ projects: Project[] }>(`/orgs/${o.id}/projects`)).projects.map((p) => ({ ...p, org: o.name }))),
    );
    return lists.flat();
  });
  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState("");
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function guarded(fn: () => Promise<unknown>) {
    setMessage(null);
    try {
      await fn();
      await keys.reload();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Request failed");
    }
  }

  return (
    <Shell>
      <h1>API keys</h1>
      <form
        className="row panel"
        onSubmit={(e) => {
          e.preventDefault();
          void guarded(async () => {
            setCreated(await api<CreatedApiKey>("/api-keys", { method: "POST", body: JSON.stringify({ name, project_id: projectId || null }) }));
            setName("");
          });
        }}
      >
        <input placeholder="Key name" value={name} onChange={(e) => setName(e.target.value)} required />
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">No project (unscoped)</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.org} / {p.name}</option>)}
        </select>
        <button>Create key</button>
      </form>
      {created && (
        <div className="panel">
          <strong className="ok">Copy this key now — it is shown only once.</strong>
          <p><code>{created.api_key}</code></p>
        </div>
      )}
      {(message || keys.error) && <p className="error">{message ?? keys.error}</p>}
      <div className="panel">
        <table>
          <thead><tr><th>Name</th><th>Prefix</th><th>Project</th><th>Last used</th><th>Status</th><th /></tr></thead>
          <tbody>
            {keys.data?.api_keys.map((k) => (
              <tr key={k.id}>
                <td>{k.name}</td>
                <td><code>{k.key_prefix}…</code></td>
                <td className="muted">{projects.data?.find((p) => p.id === k.project_id)?.name ?? (k.project_id ? k.project_id.slice(0, 8) : "—")}</td>
                <td className="muted">{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</td>
                <td>{k.revoked ? <span className="error">revoked</span> : <span className="ok">active</span>}</td>
                <td style={{ textAlign: "right" }}>
                  {!k.revoked && <button className="danger" onClick={() => guarded(() => api(`/api-keys/${k.id}`, { method: "DELETE" }))}>Revoke</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Shell>
  );
}

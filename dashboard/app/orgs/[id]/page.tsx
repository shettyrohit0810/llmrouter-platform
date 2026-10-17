"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import Shell from "@/components/Shell";
import { useLoad } from "@/components/useLoad";
import { api, ApiError } from "@/lib/api";
import type { AuditLog, Member, Org, Role } from "@/lib/types";

const ROLES: Role[] = ["viewer", "developer", "admin", "owner"];

export default function OrgPage() {
  const { id } = useParams<{ id: string }>();
  const org = useLoad(() => api<Org>(`/orgs/${id}`), [id]);
  const members = useLoad(() => api<{ members: Member[] }>(`/orgs/${id}/members`), [id]);
  const [action, setAction] = useState("");
  const audit = useLoad(
    () => api<{ logs: AuditLog[] }>(`/orgs/${id}/audit-logs?limit=50${action ? `&action=${encodeURIComponent(action)}` : ""}`),
    [id, action],
  );
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [message, setMessage] = useState<string | null>(null);

  async function guarded(fn: () => Promise<unknown>) {
    setMessage(null);
    try {
      await fn();
      await Promise.all([members.reload(), audit.reload()]);
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Request failed");
    }
  }

  return (
    <Shell>
      <h1>{org.data?.name ?? "Organization"}</h1>
      {org.error && <p className="error">{org.error}</p>}

      <h2>Members</h2>
      <form
        className="row panel"
        onSubmit={(e) => {
          e.preventDefault();
          void guarded(async () => {
            await api(`/orgs/${id}/members`, { method: "POST", body: JSON.stringify({ email, role }) });
            setEmail("");
          });
        }}
      >
        <input type="email" placeholder="Registered user's email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {ROLES.map((r) => <option key={r}>{r}</option>)}
        </select>
        <button>Add member</button>
      </form>
      {message && <p className="error">{message}</p>}
      {members.error && <p className="error">{members.error}</p>}
      <div className="panel">
        <table>
          <thead><tr><th>Email</th><th>Role</th><th /></tr></thead>
          <tbody>
            {members.data?.members.map((m) => (
              <tr key={m.user_id}>
                <td>{m.email}</td>
                <td>
                  <select
                    value={m.role}
                    onChange={(e) => guarded(() => api(`/orgs/${id}/members/${m.user_id}`, { method: "PATCH", body: JSON.stringify({ role: e.target.value }) }))}
                  >
                    {ROLES.map((r) => <option key={r}>{r}</option>)}
                  </select>
                </td>
                <td style={{ textAlign: "right" }}>
                  <button className="danger" onClick={() => guarded(() => api(`/orgs/${id}/members/${m.user_id}`, { method: "DELETE" }))}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted" style={{ marginBottom: 0 }}>Adding needs admin; changing a role needs owner.</p>
      </div>

      <h2>Audit log</h2>
      <div className="row" style={{ marginBottom: 8 }}>
        <input placeholder="Filter by action, e.g. project.created" value={action} onChange={(e) => setAction(e.target.value)} style={{ minWidth: 280 }} />
      </div>
      {audit.error && <p className="error">{audit.error} (the audit log needs the admin role)</p>}
      <div className="panel">
        <table>
          <thead><tr><th>When</th><th>Action</th><th>Resource</th><th>IP</th></tr></thead>
          <tbody>
            {audit.data?.logs.map((l) => (
              <tr key={l.id}>
                <td className="muted">{new Date(l.created_at).toLocaleString()}</td>
                <td><span className="tag">{l.action}</span></td>
                <td><code>{l.resource_type ?? "—"} {l.resource_id?.slice(0, 8) ?? ""}</code></td>
                <td className="muted">{l.ip_address ?? "—"}</td>
              </tr>
            ))}
            {audit.data?.logs.length === 0 && <tr><td colSpan={4} className="muted">No matching events.</td></tr>}
          </tbody>
        </table>
      </div>
    </Shell>
  );
}

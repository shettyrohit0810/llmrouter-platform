"use client";

import Link from "next/link";
import { useState } from "react";
import Shell from "@/components/Shell";
import { useLoad } from "@/components/useLoad";
import { api, ApiError } from "@/lib/api";
import type { Org, Project } from "@/lib/types";

type OrgWithProjects = Org & { projects: Project[] };

async function loadAll(): Promise<OrgWithProjects[]> {
  const { organizations } = await api<{ organizations: Org[] }>("/orgs");
  return Promise.all(
    organizations.map(async (o) => ({
      ...o,
      projects: (await api<{ projects: Project[] }>(`/orgs/${o.id}/projects`)).projects,
    })),
  );
}

export default function Home() {
  const { data, error, loading, reload } = useLoad(loadAll);
  const [orgName, setOrgName] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  async function guarded(fn: () => Promise<unknown>) {
    setActionError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Request failed");
    }
  }

  return (
    <Shell>
      <h1>Organizations and projects</h1>
      <form
        className="row panel"
        onSubmit={(e) => {
          e.preventDefault();
          void guarded(async () => {
            await api("/orgs", { method: "POST", body: JSON.stringify({ name: orgName }) });
            setOrgName("");
          });
        }}
      >
        <input placeholder="New organization name" value={orgName} onChange={(e) => setOrgName(e.target.value)} required />
        <button>Create organization</button>
      </form>
      {(error || actionError) && <p className="error">{error ?? actionError}</p>}
      {loading && !data && <p className="muted">Loading…</p>}
      {data?.length === 0 && <p className="muted">No organizations yet. Create one above.</p>}
      {data?.map((org) => (
        <OrgCard key={org.id} org={org} onCreateProject={(name) => guarded(() => api(`/orgs/${org.id}/projects`, { method: "POST", body: JSON.stringify({ name }) }))} />
      ))}
    </Shell>
  );
}

function OrgCard({ org, onCreateProject }: { org: OrgWithProjects; onCreateProject: (name: string) => void }) {
  const [name, setName] = useState("");
  return (
    <div className="panel">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <strong>{org.name}</strong>
        <span>
          <span className="tag">{org.plan}</span> <Link href={`/orgs/${org.id}`}>Members and audit log →</Link>
        </span>
      </div>
      <table>
        <thead><tr><th>Project</th><th>Created</th></tr></thead>
        <tbody>
          {org.projects.map((p) => (
            <tr key={p.id}>
              <td><Link href={`/projects/${p.id}`}>{p.name}</Link></td>
              <td className="muted">{new Date(p.created_at).toLocaleDateString()}</td>
            </tr>
          ))}
          {org.projects.length === 0 && <tr><td colSpan={2} className="muted">No projects</td></tr>}
        </tbody>
      </table>
      <form
        className="row"
        style={{ marginTop: 12 }}
        onSubmit={(e) => {
          e.preventDefault();
          onCreateProject(name);
          setName("");
        }}
      >
        <input placeholder="New project name" value={name} onChange={(e) => setName(e.target.value)} required />
        <button className="secondary">Add project</button>
      </form>
    </div>
  );
}

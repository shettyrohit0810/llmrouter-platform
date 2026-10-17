"use client";

import { useState } from "react";
import Shell from "@/components/Shell";
import { useLoad } from "@/components/useLoad";
import { api, ApiError } from "@/lib/api";
import type { RegistryRouter, RouterVersion } from "@/lib/types";

export default function RegistryPage() {
  const routers = useLoad(() => api<{ routers: RegistryRouter[] }>("/registry/routers"));
  const [selected, setSelected] = useState<string | null>(null);
  const versions = useLoad(
    () => (selected ? api<{ versions: RouterVersion[] }>(`/registry/router-versions?router_name=${encodeURIComponent(selected)}`) : Promise.resolve({ versions: [] })),
    [selected],
  );
  const [message, setMessage] = useState<string | null>(null);

  async function archive(id: string) {
    setMessage(null);
    try {
      await api(`/registry/router-versions/${id}/archive`, { method: "POST" });
      await versions.reload();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Request failed");
    }
  }

  return (
    <Shell>
      <h1>Model registry</h1>
      {routers.error && <p className="error">{routers.error}</p>}
      <div className="panel">
        <table>
          <thead><tr><th>Router</th><th>Trainable</th><th>Status</th><th /></tr></thead>
          <tbody>
            {routers.data?.routers.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>{r.trainable ? "yes" : "no"}</td>
                <td><span className="tag">{r.status}</span></td>
                <td style={{ textAlign: "right" }}><button className="secondary" onClick={() => setSelected(r.name)}>Versions</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <>
          <h2>Versions of {selected}</h2>
          {message && <p className="error">{message}</p>}
          {versions.error && <p className="error">{versions.error}</p>}
          <div className="panel">
            <table>
              <thead><tr><th>Label</th><th>Checkpoint</th><th>Status</th><th>Created</th><th /></tr></thead>
              <tbody>
                {versions.data?.versions.map((v) => (
                  <tr key={v.id}>
                    <td>{v.version_label}</td>
                    <td><code>{v.checkpoint_path}</code></td>
                    <td><span className="tag">{v.status}</span></td>
                    <td className="muted">{new Date(v.created_at).toLocaleString()}</td>
                    <td style={{ textAlign: "right" }}>
                      {v.status === "active" && <button className="danger" onClick={() => archive(v.id)}>Archive</button>}
                    </td>
                  </tr>
                ))}
                {versions.data?.versions.length === 0 && <tr><td colSpan={5} className="muted">No trained versions yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Shell>
  );
}

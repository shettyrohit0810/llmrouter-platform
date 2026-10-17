"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getTokens, logout } from "@/lib/api";

/** Page chrome plus an auth gate: no stored session -> /login. */
export default function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getTokens()) router.replace("/login");
    else setReady(true);
  }, [router]);

  async function signOut() {
    await logout();
    router.replace("/login");
  }

  if (!ready) return null;
  return (
    <>
      <nav>
        <Link href="/" className="brand">LLMRouter Console</Link>
        <Link href="/">Projects</Link>
        <Link href="/registry">Registry</Link>
        <Link href="/keys">API keys</Link>
        <span className="spacer" />
        <button className="secondary" onClick={signOut}>Sign out</button>
      </nav>
      <main>{children}</main>
    </>
  );
}

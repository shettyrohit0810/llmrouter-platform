const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
const KEY = "llmrouter.tokens";

type Tokens = { access_token: string; refresh_token: string };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getTokens(): Tokens | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

export function setTokens(tokens: Tokens | null): void {
  if (tokens) window.localStorage.setItem(KEY, JSON.stringify(tokens));
  else window.localStorage.removeItem(KEY);
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body.error ?? body.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}

async function refresh(tokens: Tokens): Promise<Tokens | null> {
  const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  });
  if (!res.ok) return null;
  const next = (await res.json()) as Tokens;
  setTokens(next);
  return next;
}

async function request(path: string, init: RequestInit, tokens: Tokens | null): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (tokens) headers.set("Authorization", `Bearer ${tokens.access_token}`);
  return fetch(`${BASE}/api/v1${path}`, { ...init, headers });
}

/** JSON request to /api/v1. Refreshes the access token once on a 401. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let tokens = getTokens();
  let res = await request(path, init, tokens);
  if (res.status === 401 && tokens) {
    tokens = await refresh(tokens);
    if (!tokens) {
      setTokens(null);
      throw new ApiError(401, "Session expired");
    }
    res = await request(path, init, tokens);
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function login(email: string, password: string): Promise<void> {
  const tokens = await api<Tokens>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setTokens(tokens);
}

export async function register(email: string, password: string): Promise<void> {
  await api("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) });
  await login(email, password);
}

export async function logout(): Promise<void> {
  const tokens = getTokens();
  if (tokens) {
    try {
      await api("/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: tokens.refresh_token }),
      });
    } catch {
      /* logging out locally regardless */
    }
  }
  setTokens(null);
}

import "server-only";

import { createClient } from "@/lib/supabase/server";

export const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? process.env.BACKEND_URL ?? "https://datatools.sjri.res.in/ADAM";

export async function getBackendAccessToken() {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  return session?.access_token ?? null;
}

// Keeps a single flaky Vercel->VM round trip from surfacing as a hard error
// banner: a short per-attempt timeout (well under Vercel's own function
// timeout) plus bounded retries with backoff+jitter -- for idempotent GETs
// only. Non-GET requests get exactly one attempt, never retried: a
// slow-but-actually-successful write must not be resent, and this backend

const FETCH_TIMEOUT_MS = 4_000;
const MAX_ATTEMPTS = 2; // 1 initial + 1 retry, GET only.
const RETRYABLE_STATUS = new Set([502, 503, 504]); // upstream-unavailable, not an application error

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function backoffDelayMs(retryIndex: number): number {
  return 300 * 2 ** retryIndex + Math.random() * 150;
}

export async function backendJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);

  if (!headers.has("Authorization")) {
    const token = await getBackendAccessToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  const method = (init?.method ?? "GET").toUpperCase();
  const retryable = method === "GET";
  const url = `${BACKEND_URL}${path}`;
  const fetchInit: RequestInit = { ...init, headers, cache: "no-store" };

  const attempts = retryable ? MAX_ATTEMPTS : 1;
  let res: Response | null = null;
  let lastErr: unknown = null;

  for (let attempt = 0; attempt < attempts; attempt++) {
    if (attempt > 0) await sleep(backoffDelayMs(attempt - 1));
    try {
      res = await fetchWithTimeout(url, fetchInit, FETCH_TIMEOUT_MS);
    } catch (err) {
      lastErr = err;
      res = null;
      continue;
    }
    if (res.ok || !RETRYABLE_STATUS.has(res.status) || attempt === attempts - 1) break;
  }

  if (!res) throw lastErr instanceof Error ? lastErr : new Error("Request failed");

  const text = await res.text();
  let json: unknown;
  try {
    json = text ? JSON.parse(text) : {};
  } catch {
    json = { detail: text?.slice(0, 300) ?? "Empty response" };
  }

  if (!res.ok) {
    const detail = typeof json === "object" && json && "detail" in json ? String(json.detail) : "Request failed";
    throw new Error(detail);
  }

  return json as T;
}

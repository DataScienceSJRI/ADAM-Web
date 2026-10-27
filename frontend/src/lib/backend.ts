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
// timeout) plus one retry for idempotent GETs. Non-GET requests are never
// retried -- a slow-but-successful write must not be resent.
const FETCH_TIMEOUT_MS = 6_000;

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
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
  const url = `${BACKEND_URL}${path}`;
  const fetchInit: RequestInit = { ...init, headers, cache: "no-store" };

  let res: Response;
  try {
    res = await fetchWithTimeout(url, fetchInit, FETCH_TIMEOUT_MS);
  } catch (err) {
    if (method !== "GET") throw err;
    res = await fetchWithTimeout(url, fetchInit, FETCH_TIMEOUT_MS);
  }

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

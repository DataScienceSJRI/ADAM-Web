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

export async function backendJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);

  if (!headers.has("Authorization")) {
    const token = await getBackendAccessToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

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

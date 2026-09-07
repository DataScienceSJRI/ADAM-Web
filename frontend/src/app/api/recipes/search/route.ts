import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL, getBackendAccessToken } from "@/lib/backend";

export async function GET(req: NextRequest) {
  const token = await getBackendAccessToken();
  const auth = req.headers.get("authorization") ?? (token ? `Bearer ${token}` : null);
  const q = req.nextUrl.searchParams.get("q") ?? "";
  const pageSize = req.nextUrl.searchParams.get("page_size") ?? "10";
  try {
    const res = await fetch(
      `${BACKEND_URL}/api/v1/recipes/search?q=${encodeURIComponent(q)}&page_size=${pageSize}`,
      { headers: { ...(auth ? { Authorization: auth } : {}) } }
    );
    const text = await res.text();
    let json: unknown;
    try { json = text ? JSON.parse(text) : {}; } catch { json = { detail: text?.slice(0, 300) }; }
    return NextResponse.json(json, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Could not reach backend" }, { status: 503 });
  }
}

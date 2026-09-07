import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL, getBackendAccessToken } from "@/lib/backend";

export async function GET(req: NextRequest) {
  const token = await getBackendAccessToken();
  const auth = req.headers.get("authorization") ?? (token ? `Bearer ${token}` : null);
  try {
    const res = await fetch(`${BACKEND_URL}/api/v1/feedback/reviews`, {
      headers: { ...(auth ? { Authorization: auth } : {}) },
    });
    const text = await res.text();
    let json: unknown;
    try { json = text ? JSON.parse(text) : []; } catch { json = { detail: text?.slice(0, 300) }; }
    return NextResponse.json(json, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Could not reach backend" }, { status: 503 });
  }
}

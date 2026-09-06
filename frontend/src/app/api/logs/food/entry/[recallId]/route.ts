import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL, getBackendAccessToken } from "@/lib/backend";

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ recallId: string }> }
) {
  const { recallId } = await params;
  const token = await getBackendAccessToken();
  const auth = req.headers.get("authorization") ?? (token ? `Bearer ${token}` : null);
  try {
    const res = await fetch(`${BACKEND_URL}/api/v1/recall/coordinator/${recallId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...(auth ? { Authorization: auth } : {}),
      },
      body: await req.text(),
    });
    const text = await res.text();
    let json: unknown;
    try { json = text ? JSON.parse(text) : {}; } catch { json = { detail: text?.slice(0, 300) }; }
    return NextResponse.json(json, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Could not reach backend" }, { status: 503 });
  }
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ recallId: string }> }
) {
  const { recallId } = await params;
  const token = await getBackendAccessToken();
  const auth = req.headers.get("authorization") ?? (token ? `Bearer ${token}` : null);
  try {
    const res = await fetch(`${BACKEND_URL}/api/v1/recall/coordinator/${recallId}`, {
      method: "DELETE",
      headers: { ...(auth ? { Authorization: auth } : {}) },
    });
    if (res.status === 204) return new NextResponse(null, { status: 204 });
    const text = await res.text();
    let json: unknown;
    try { json = text ? JSON.parse(text) : {}; } catch { json = { detail: text?.slice(0, 300) }; }
    return NextResponse.json(json, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Could not reach backend" }, { status: 503 });
  }
}

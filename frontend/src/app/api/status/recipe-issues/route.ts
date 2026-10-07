import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? process.env.BACKEND_URL ?? "https://datatools.sjri.res.in/ADAM";

// Read-only list. The dashboard token travels as ?token= (same gate as the
// overview). Marking fixed/reopened is a separate POST that needs a coordinator login.
export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get("token") ?? "";
  try {
    const res = await fetch(`${BACKEND}/api/v1/status/recipe-issues/${encodeURIComponent(token)}`);
    const text = await res.text();
    let json: unknown;
    try { json = text ? JSON.parse(text) : {}; } catch { json = { detail: text?.slice(0, 300) }; }
    return NextResponse.json(json, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Could not reach backend" }, { status: 503 });
  }
}

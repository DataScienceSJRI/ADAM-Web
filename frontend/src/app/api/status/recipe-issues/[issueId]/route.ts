import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? process.env.BACKEND_URL ?? "https://datatools.sjri.res.in/ADAM";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ issueId: string }> }
) {
  const { issueId } = await params;
  const body = await req.text();
  try {
    const res = await fetch(`${BACKEND}/api/v1/status/recipe-issues/${encodeURIComponent(issueId)}/status`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: req.headers.get("authorization") ?? "",
      },
      body,
    });
    const text = await res.text();
    let json: unknown;
    try { json = text ? JSON.parse(text) : {}; } catch { json = { detail: text?.slice(0, 300) }; }
    return NextResponse.json(json, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Could not reach backend" }, { status: 503 });
  }
}

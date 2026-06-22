import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? process.env.BACKEND_URL ?? "https://datatools.sjri.res.in/ADAM";

export async function GET(req: NextRequest) {
  const auth = req.headers.get("authorization");
  const q = req.nextUrl.searchParams.get("q") ?? "";
  const pageSize = req.nextUrl.searchParams.get("page_size") ?? "10";
  try {
    const res = await fetch(
      `${BACKEND}/api/v1/recipes/search?q=${encodeURIComponent(q)}&page_size=${pageSize}`,
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

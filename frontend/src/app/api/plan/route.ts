import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "https://datatools.sjri.res.in/ADAM";

export async function POST(req: NextRequest) {
  const auth = req.headers.get("authorization");
  const body = await req.text();

  try {
    const upstream = await fetch(`${BACKEND}/api/v1/plan`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(auth ? { Authorization: auth } : {}),
      },
      body,
    });

    const json = await upstream.json().catch(() => ({ detail: "Empty response from backend" }));
    return NextResponse.json(json, { status: upstream.status });
  } catch {
    return NextResponse.json(
      { detail: "Could not reach the plan generation server — please try again." },
      { status: 503 },
    );
  }
}

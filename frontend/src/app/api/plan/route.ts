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

    const text = await upstream.text();
    let json: unknown;
    try {
      json = text ? JSON.parse(text) : { detail: "Empty response from backend" };
    } catch {
      json = {
        detail: text
          ? `Backend returned a non-JSON response: ${text.slice(0, 300)}`
          : "Empty response from backend",
      };
    }
    return NextResponse.json(json, { status: upstream.status });
  } catch {
    return NextResponse.json(
      { detail: "Could not reach the plan generation server — please try again." },
      { status: 503 },
    );
  }
}

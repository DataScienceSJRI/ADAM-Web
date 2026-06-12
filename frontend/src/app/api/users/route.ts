import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "https://datatools.sjri.res.in/ADAM";

async function proxy(req: NextRequest, method: string, body?: string) {
  const auth = req.headers.get("authorization");
  try {
    const upstream = await fetch(`${BACKEND}/api/v1/users`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(auth ? { Authorization: auth } : {}),
      },
      ...(body ? { body } : {}),
    });
    const text = await upstream.text();
    let json: unknown;
    try {
      json = text ? JSON.parse(text) : {};
    } catch {
      json = { detail: text?.slice(0, 300) ?? "Empty response" };
    }
    return NextResponse.json(json, { status: upstream.status });
  } catch {
    return NextResponse.json({ detail: "Could not reach backend" }, { status: 503 });
  }
}

export async function GET(req: NextRequest) {
  return proxy(req, "GET");
}

export async function POST(req: NextRequest) {
  return proxy(req, "POST", await req.text());
}

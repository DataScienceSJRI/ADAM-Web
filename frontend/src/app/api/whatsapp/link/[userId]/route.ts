import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "https://datatools.sjri.res.in/ADAM";

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ userId: string }> }
) {
  const { userId } = await params;
  const auth = req.headers.get("authorization");
  try {
    const upstream = await fetch(`${BACKEND}/api/v1/whatsapp/link/${userId}`, {
      method: "DELETE",
      headers: { ...(auth ? { Authorization: auth } : {}) },
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

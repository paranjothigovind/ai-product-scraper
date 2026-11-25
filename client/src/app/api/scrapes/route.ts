import { NextResponse, type NextRequest } from "next/server";
import { forward } from "@/lib/proxy";

// The backend caps pasted HTML at 1 MB; refuse anything much larger before forwarding it.
const MAX_BODY_BYTES = 1_200_000;

export async function POST(req: NextRequest) {
  const body = await req.text();
  if (Buffer.byteLength(body) > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: "Request is too large." }, { status: 413 });
  }
  return forward("/v1/scrapes", {
    method: "POST",
    body,
    idempotencyKey: req.headers.get("idempotency-key"),
  });
}

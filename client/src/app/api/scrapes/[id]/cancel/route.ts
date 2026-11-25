import { NextResponse } from "next/server";
import { forward, isUuid } from "@/lib/proxy";

export async function POST(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) return NextResponse.json({ detail: "run not found" }, { status: 404 });
  return forward(`/v1/scrapes/${id}/cancel`, { method: "POST" });
}

import { NextResponse } from "next/server";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TIMEOUT_MS = 15_000;

export function isUuid(value: string): boolean {
  return UUID.test(value);
}

/**
 * Forwards a request to the backend. The API token lives only in this server process, so the
 * browser never sees it and never talks to the backend directly (no CORS to configure).
 */
export async function forward(
  path: string,
  init: { method: "GET" | "POST"; body?: string; idempotencyKey?: string | null },
): Promise<NextResponse> {
  const base = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;
  if (process.env.API_TOKEN) headers.Authorization = `Bearer ${process.env.API_TOKEN}`;

  let upstream: Response;
  try {
    upstream = await fetch(`${base}${path}`, {
      method: init.method,
      headers,
      body: init.body,
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    return NextResponse.json({ detail: "The scraper API is not reachable." }, { status: 502 });
  }

  const text = await upstream.text();
  try {
    return NextResponse.json(JSON.parse(text), { status: upstream.status });
  } catch {
    // Never pass through a non-JSON body: it could be an HTML error page from a proxy.
    return NextResponse.json({ detail: "Unexpected response from the API." }, { status: 502 });
  }
}

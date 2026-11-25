import type { Run, ScrapeInput } from "./types";

/** An error with a message that is safe to show the user. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** The backend's `detail` is a string, or a list of validation problems. */
export function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item: unknown) => {
      if (item && typeof item === "object") {
        const { loc, msg } = item as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(loc) ? loc.filter((p) => p !== "body").join(".") : "";
        const text = (msg ?? "invalid").replace(/^Value error, /, "");
        return field ? `${field}: ${text}` : text;
      }
      return String(item);
    });
    return parts.join("; ");
  }
  return "Something went wrong.";
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, cache: "no-store" });
  } catch {
    if (init.signal?.aborted) throw new DOMException("aborted", "AbortError");
    throw new ApiError("Could not reach the server. Check your connection.", 0);
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : null;
    throw new ApiError(describeDetail(detail), res.status);
  }
  return body as T;
}

export function createScrape(
  input: ScrapeInput,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<{ id: string; status: string; created: boolean }> {
  return request("/api/scrapes", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(input),
    signal,
  });
}

export function getScrape(id: string, signal?: AbortSignal): Promise<Run> {
  return request(`/api/scrapes/${id}`, { method: "GET", signal });
}

export function cancelScrape(id: string, signal?: AbortSignal): Promise<Run> {
  return request(`/api/scrapes/${id}/cancel`, { method: "POST", signal });
}

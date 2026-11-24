import type { ErrorCode } from "../schemas/errors";

export class ScrapeError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly details: { status?: number; retryAfterSeconds?: number } = {},
  ) {
    super(message);
    this.name = "ScrapeError";
  }
}

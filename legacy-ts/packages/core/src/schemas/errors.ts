import { z } from "zod";

export const ErrorCode = z.enum([
  "invalid_input",
  "blocked",
  "robots_disallowed",
  "timeout",
  "fetch_failed",
  "render_failed",
  "no_products_found",
  "llm_failed",
  "budget_exceeded",
  "internal",
]);
export type ErrorCode = z.infer<typeof ErrorCode>;

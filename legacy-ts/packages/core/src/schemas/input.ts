import { z } from "zod";

const MAX_HTML_BYTES = 1_000_000;
const MAX_URL_CHARS = 2048;

const byteLength = (s: string) => new TextEncoder().encode(s).length;

// A factory because the product cap comes from env (PLAN_CAP_PRODUCTS).
export function createScrapeInputSchema(planCapProducts: number) {
  return z
    .object({
      url: z
        .string()
        .max(MAX_URL_CHARS)
        .url()
        .refine((u) => /^https?:\/\//i.test(u), "only http and https URLs are allowed")
        .optional(),
      html: z
        .string()
        .min(1)
        .refine((h) => byteLength(h) <= MAX_HTML_BYTES, "html exceeds 1MB")
        .optional(),
      maxProducts: z.number().int().min(1).max(planCapProducts),
      scope: z.enum(["category", "site"]).default("category"),
      maxPages: z.number().int().positive().optional(),
      maxDepth: z.number().int().min(0).max(5).default(2),
    })
    .strict()
    .refine((v) => (v.url === undefined) !== (v.html === undefined), {
      message: "provide exactly one of url or html",
      path: ["url"],
    });
}
export type ScrapeInput = z.infer<ReturnType<typeof createScrapeInputSchema>>;

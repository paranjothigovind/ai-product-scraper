import { z } from "zod";
import { EvalReport } from "./eval";
import { ErrorCode } from "./errors";
import { Category, RankedProduct } from "./product";

export const SCHEMA_VERSION = 1;

export const ScrapeResult = z.object({
  schemaVersion: z.literal(SCHEMA_VERSION),
  sourceUrl: z.string().nullable(), // null for raw-HTML input
  scrapedAt: z.string().datetime(),
  pagesFetched: z.number().int().nonnegative(),
  requested: z.number().int().positive(),
  products: z.array(RankedProduct),
  categories: z.array(Category),
  evaluation: EvalReport,
  confidence: z.enum(["high", "medium", "low"]),
  incomplete: z.boolean(),
  invalidCount: z.number().int().nonnegative(),
  errorCode: ErrorCode.optional(),
});
export type ScrapeResult = z.infer<typeof ScrapeResult>;

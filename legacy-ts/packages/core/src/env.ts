import { z } from "zod";

const positiveInt = (def: number) => z.coerce.number().int().positive().default(def);

const EnvSchema = z.object({
  ANTHROPIC_API_KEY: z.string().min(1),
  MODEL_EXTRACT: z.string().min(1),
  MODEL_JUDGE: z.string().min(1),
  MODEL_ESCALATE: z.string().min(1),
  DATABASE_URL: z.string().url(),
  REDIS_URL: z.string().url(),
  S3_ENDPOINT: z.string().url(),
  S3_REGION: z.string().min(1).default("us-east-1"),
  S3_BUCKET: z.string().min(1),
  S3_ACCESS_KEY_ID: z.string().min(1),
  S3_SECRET_ACCESS_KEY: z.string().min(1),
  MAX_PAGES_TOTAL: positiveInt(50),
  MAX_RETRIES: z.coerce.number().int().min(0).default(2),
  // TODO(next): spec gave no default; 200k is a placeholder until phase 4 measures real usage.
  MAX_TOKENS_PER_RUN: positiveInt(200_000),
  MIN_QUALITY: z.coerce.number().min(0).max(1).default(0.75),
  PLAN_CAP_PRODUCTS: positiveInt(500),
});
export type Env = z.infer<typeof EnvSchema>;

/** Fails fast reporting variable names and reasons only; values (secrets) are never printed. */
export function loadEnv(source: Record<string, string | undefined> = process.env): Env {
  const parsed = EnvSchema.safeParse(source);
  if (!parsed.success) {
    const problems = parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; ");
    throw new Error(`Invalid environment: ${problems}`);
  }
  return parsed.data;
}

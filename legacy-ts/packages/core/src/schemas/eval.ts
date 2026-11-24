import { z } from "zod";

const Metric = z.number().min(0).max(1);

export const EvalReport = z.object({
  score: Metric,
  metrics: z.object({
    schemaValidity: Metric,
    fieldCoverage: Metric,
    plausibility: Metric,
    volume: Metric,
    // Null when the judge was skipped (budget exhausted or nothing to sample).
    groundedness: Metric.nullable(),
  }),
  issues: z.array(z.string()),
  decision: z.enum(["accept", "retry", "low_confidence"]),
  feedback: z.string(),
});
export type EvalReport = z.infer<typeof EvalReport>;

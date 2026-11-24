import {
  doublePrecision,
  index,
  integer,
  jsonb,
  pgTable,
  primaryKey,
  serial,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";

// Every query must filter by runs.user_id; child tables are reached through run_id.
// TODO(next): separate web/worker DB roles and grants (phase 11/12).
export const runs = pgTable(
  "runs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: text("user_id").notNull(),
    idempotencyKey: text("idempotency_key"),
    inputType: text("input_type", { enum: ["url", "html"] }).notNull(),
    inputHash: text("input_hash").notNull(),
    sourceUrl: text("source_url"),
    status: text("status", {
      enum: ["queued", "running", "succeeded", "failed", "low_confidence", "cancelled"],
    })
      .notNull()
      .default("queued"),
    requested: integer("requested").notNull(),
    score: doublePrecision("score"),
    confidence: text("confidence", { enum: ["high", "medium", "low"] }),
    pagesFetched: integer("pages_fetched").notNull().default(0),
    tokensIn: integer("tokens_in").notNull().default(0),
    tokensOut: integer("tokens_out").notNull().default(0),
    costUsd: doublePrecision("cost_usd").notNull().default(0),
    errorCode: text("error_code"),
    schemaVersion: integer("schema_version").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
  },
  (t) => [
    index("runs_user_created_idx").on(t.userId, t.createdAt),
    uniqueIndex("runs_user_idem_idx").on(t.userId, t.idempotencyKey),
  ],
);

export const runPages = pgTable(
  "run_pages",
  {
    runId: uuid("run_id")
      .notNull()
      .references(() => runs.id, { onDelete: "cascade" }),
    pageNo: integer("page_no").notNull(),
    url: text("url").notNull(),
    fetchTier: text("fetch_tier", { enum: ["static", "render"] }).notNull(),
    httpStatus: integer("http_status"),
    bytes: integer("bytes"),
    htmlRef: text("html_ref"), // S3 key, 7-day TTL
    durationMs: integer("duration_ms"),
  },
  (t) => [primaryKey({ columns: [t.runId, t.pageNo] })],
);

export const products = pgTable(
  "products",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    runId: uuid("run_id")
      .notNull()
      .references(() => runs.id, { onDelete: "cascade" }),
    rank: integer("rank"),
    score: doublePrecision("score"),
    reason: text("reason"),
    canonicalUrl: text("canonical_url").notNull(),
    name: text("name").notNull(),
    price: doublePrecision("price"),
    currency: text("currency"),
    image: text("image"),
    brand: text("brand"),
    category: text("category"),
    rating: doublePrecision("rating"),
    reviewCount: integer("review_count"),
    availability: text("availability", { enum: ["in_stock", "out_of_stock", "unknown"] }).notNull(),
    description: text("description"),
    source: text("source", { enum: ["jsonld", "microdata", "selector", "llm"] }).notNull(),
  },
  // Idempotency key: a resumed node upserts instead of duplicating.
  (t) => [uniqueIndex("products_run_url_idx").on(t.runId, t.canonicalUrl)],
);

export const categories = pgTable(
  "categories",
  {
    id: serial("id").primaryKey(),
    runId: uuid("run_id")
      .notNull()
      .references(() => runs.id, { onDelete: "cascade" }),
    name: text("name").notNull(),
    slug: text("slug").notNull(),
    url: text("url"),
    parent: text("parent"),
    productCount: integer("product_count"),
  },
  (t) => [uniqueIndex("categories_run_slug_idx").on(t.runId, t.slug)],
);

export const evalReports = pgTable(
  "eval_reports",
  {
    runId: uuid("run_id")
      .notNull()
      .references(() => runs.id, { onDelete: "cascade" }),
    attempt: integer("attempt").notNull(),
    score: doublePrecision("score").notNull(),
    metricsJson: jsonb("metrics_json").notNull(),
    issuesJson: jsonb("issues_json").notNull(),
    decision: text("decision", { enum: ["accept", "retry", "low_confidence"] }).notNull(),
    feedback: text("feedback"),
  },
  (t) => [primaryKey({ columns: [t.runId, t.attempt] })],
);

export const traceEvents = pgTable(
  "trace_events",
  {
    runId: uuid("run_id")
      .notNull()
      .references(() => runs.id, { onDelete: "cascade" }),
    seq: integer("seq").notNull(),
    node: text("node").notNull(),
    startedAt: timestamp("started_at", { withTimezone: true }).notNull(),
    durationMs: integer("duration_ms").notNull(),
    inCount: integer("in_count"),
    outCount: integer("out_count"),
    metaJson: jsonb("meta_json"),
  },
  (t) => [primaryKey({ columns: [t.runId, t.seq] })],
);

CREATE TABLE "categories" (
	"id" serial PRIMARY KEY NOT NULL,
	"run_id" uuid NOT NULL,
	"name" text NOT NULL,
	"slug" text NOT NULL,
	"url" text,
	"parent" text,
	"product_count" integer
);
--> statement-breakpoint
CREATE TABLE "eval_reports" (
	"run_id" uuid NOT NULL,
	"attempt" integer NOT NULL,
	"score" double precision NOT NULL,
	"metrics_json" jsonb NOT NULL,
	"issues_json" jsonb NOT NULL,
	"decision" text NOT NULL,
	"feedback" text,
	CONSTRAINT "eval_reports_run_id_attempt_pk" PRIMARY KEY("run_id","attempt")
);
--> statement-breakpoint
CREATE TABLE "products" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"run_id" uuid NOT NULL,
	"rank" integer,
	"score" double precision,
	"reason" text,
	"canonical_url" text NOT NULL,
	"name" text NOT NULL,
	"price" double precision,
	"currency" text,
	"image" text,
	"brand" text,
	"category" text,
	"rating" double precision,
	"review_count" integer,
	"availability" text NOT NULL,
	"description" text,
	"source" text NOT NULL
);
--> statement-breakpoint
CREATE TABLE "run_pages" (
	"run_id" uuid NOT NULL,
	"page_no" integer NOT NULL,
	"url" text NOT NULL,
	"fetch_tier" text NOT NULL,
	"http_status" integer,
	"bytes" integer,
	"html_ref" text,
	"duration_ms" integer,
	CONSTRAINT "run_pages_run_id_page_no_pk" PRIMARY KEY("run_id","page_no")
);
--> statement-breakpoint
CREATE TABLE "runs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" text NOT NULL,
	"idempotency_key" text,
	"input_type" text NOT NULL,
	"input_hash" text NOT NULL,
	"source_url" text,
	"status" text DEFAULT 'queued' NOT NULL,
	"requested" integer NOT NULL,
	"score" double precision,
	"confidence" text,
	"pages_fetched" integer DEFAULT 0 NOT NULL,
	"tokens_in" integer DEFAULT 0 NOT NULL,
	"tokens_out" integer DEFAULT 0 NOT NULL,
	"cost_usd" double precision DEFAULT 0 NOT NULL,
	"error_code" text,
	"schema_version" integer NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"finished_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "trace_events" (
	"run_id" uuid NOT NULL,
	"seq" integer NOT NULL,
	"node" text NOT NULL,
	"started_at" timestamp with time zone NOT NULL,
	"duration_ms" integer NOT NULL,
	"in_count" integer,
	"out_count" integer,
	"meta_json" jsonb,
	CONSTRAINT "trace_events_run_id_seq_pk" PRIMARY KEY("run_id","seq")
);
--> statement-breakpoint
ALTER TABLE "categories" ADD CONSTRAINT "categories_run_id_runs_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "eval_reports" ADD CONSTRAINT "eval_reports_run_id_runs_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "products" ADD CONSTRAINT "products_run_id_runs_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_pages" ADD CONSTRAINT "run_pages_run_id_runs_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "trace_events" ADD CONSTRAINT "trace_events_run_id_runs_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "categories_run_slug_idx" ON "categories" USING btree ("run_id","slug");--> statement-breakpoint
CREATE UNIQUE INDEX "products_run_url_idx" ON "products" USING btree ("run_id","canonical_url");--> statement-breakpoint
CREATE INDEX "runs_user_created_idx" ON "runs" USING btree ("user_id","created_at");--> statement-breakpoint
CREATE UNIQUE INDEX "runs_user_idem_idx" ON "runs" USING btree ("user_id","idempotency_key");
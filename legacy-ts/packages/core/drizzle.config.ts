import { defineConfig } from "drizzle-kit";

export default defineConfig({
  dialect: "postgresql",
  schema: "./src/db/schema.ts",
  out: "./drizzle",
  // Only needed for push/studio; generate works offline.
  dbCredentials: { url: process.env.DATABASE_URL ?? "postgres://localhost/scraper" },
});

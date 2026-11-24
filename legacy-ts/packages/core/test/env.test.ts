import { describe, expect, it } from "vitest";
import { loadEnv } from "../src/env";

const valid = {
  ANTHROPIC_API_KEY: "sk-test-secret",
  MODEL_EXTRACT: "a",
  MODEL_JUDGE: "b",
  MODEL_ESCALATE: "c",
  DATABASE_URL: "postgres://u:p@localhost:5432/db",
  REDIS_URL: "redis://localhost:6379",
  S3_ENDPOINT: "http://localhost:9000",
  S3_BUCKET: "bkt",
  S3_ACCESS_KEY_ID: "k",
  S3_SECRET_ACCESS_KEY: "s",
};

describe("loadEnv", () => {
  it("applies spec defaults", () => {
    const env = loadEnv(valid);
    expect(env.MAX_PAGES_TOTAL).toBe(50);
    expect(env.MAX_RETRIES).toBe(2);
    expect(env.MIN_QUALITY).toBe(0.75);
    expect(env.PLAN_CAP_PRODUCTS).toBe(500);
  });

  it("coerces numeric strings", () => {
    expect(loadEnv({ ...valid, MAX_PAGES_TOTAL: "10" }).MAX_PAGES_TOTAL).toBe(10);
  });

  it("fails on missing vars without leaking values", () => {
    const rest: Record<string, string | undefined> = { ...valid, DATABASE_URL: "not-a-url-secret" };
    delete rest.ANTHROPIC_API_KEY;
    expect(() => loadEnv(rest)).toThrow(/ANTHROPIC_API_KEY/);
    expect(() => loadEnv(rest)).not.toThrow(/not-a-url-secret/);
  });
});

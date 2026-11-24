import http from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createScrapeHtml } from "../src/tools/scrape-html";
import { isBlockedIp } from "../src/tools/ssrf";

let server: http.Server;
let port: number;
let resolveCalls: string[] = [];

beforeAll(async () => {
  server = http.createServer((req, res) => {
    const path = req.url ?? "/";
    const html = (body: string, status = 200, headers: Record<string, string> = {}) => {
      res.writeHead(status, { "content-type": "text/html", ...headers });
      res.end(body);
    };
    if (path === "/ok") return html("<html><body>hello</body></html>");
    if (path === "/403") return html("no", 403);
    if (path === "/429") return html("slow down", 429, { "retry-after": "120" });
    if (path === "/500") return html("boom", 500);
    if (path === "/404") return html("<html>gone</html>", 404);
    if (path === "/captcha") return html('<div class="g-recaptcha"></div>');
    if (path === "/json") {
      res.writeHead(200, { "content-type": "application/json" });
      return res.end("{}");
    }
    if (path === "/big") return html("x".repeat(3 * 1024 * 1024));
    if (path === "/slow") return void setTimeout(() => html("late"), 500);
    if (path === "/to-ok") return html("", 302, { location: "/ok" });
    if (path === "/to-meta") return html("", 302, { location: "http://169.254.169.254/latest/meta-data/" });
    if (path === "/to-file") return html("", 302, { location: "file:///etc/passwd" });
    if (path === "/to-odd-port") return html("", 302, { location: `http://127.0.0.1:${port + 1}/` });
    if (path === "/to-private-name") return html("", 302, { location: "http://internal.test/" });
    if (path === "/loop") return html("", 302, { location: "/loop" });
    html("not found", 404);
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  port = (server.address() as AddressInfo).port;
});
afterAll(() => new Promise<void>((r) => server.close(() => r())));

// Test-only policy: loopback is allowed so we can reach the local server; everything else stays blocked.
const make = (extra = {}) =>
  createScrapeHtml({
    resolve: async (host) => {
      resolveCalls.push(host);
      if (host === "internal.test") return [{ address: "10.0.0.1", family: 4 }];
      return [{ address: "127.0.0.1", family: 4 }]; // every name "resolves" to the local server
    },
    isAllowedIp: (ip) => ip === "127.0.0.1" || !isBlockedIp(ip),
    ...extra,
  });
const url = (p: string) => `http://site.test:${port}${p}`;
const scraper = (extra = {}) => make({ allowedPorts: [80, 443, port], ...extra });

describe("scrapeHtml (static tier)", () => {
  it("fetches HTML and connects to the validated IP, not system DNS", async () => {
    resolveCalls = [];
    const r = await scraper()({ url: url("/ok") });
    expect(r).toMatchObject({ status: 200, tier: "static", finalUrl: url("/ok") });
    expect(r.html).toContain("hello");
    expect(resolveCalls).toEqual(["site.test"]); // "site.test" has no real DNS; the pin made this work
  });

  it("re-resolves and re-validates on each redirect hop", async () => {
    resolveCalls = [];
    const r = await scraper()({ url: url("/to-ok") });
    expect(r.finalUrl).toBe(url("/ok"));
    expect(resolveCalls.length).toBe(2);
  });

  it("rejects a redirect to the metadata endpoint", async () => {
    await expect(scraper()({ url: url("/to-meta") })).rejects.toMatchObject({ code: "invalid_input" });
  });

  it("rejects a redirect to file://", async () => {
    await expect(scraper()({ url: url("/to-file") })).rejects.toMatchObject({ code: "invalid_input" });
  });

  it("rejects a redirect to a disallowed port", async () => {
    await expect(scraper()({ url: url("/to-odd-port") })).rejects.toMatchObject({ code: "invalid_input" });
  });

  it("rejects a redirect to a name that resolves privately", async () => {
    await expect(scraper()({ url: url("/to-private-name") })).rejects.toMatchObject({ code: "invalid_input" });
  });

  it("stops redirect loops after 5 hops", async () => {
    await expect(scraper()({ url: url("/loop") })).rejects.toMatchObject({ code: "fetch_failed", message: "too many redirects" });
  });

  it("maps 403 and 429 to blocked and surfaces Retry-After", async () => {
    await expect(scraper()({ url: url("/403") })).rejects.toMatchObject({ code: "blocked" });
    await expect(scraper()({ url: url("/429") })).rejects.toMatchObject({
      code: "blocked",
      details: { status: 429, retryAfterSeconds: 120 },
    });
  });

  it("detects bot challenge pages as blocked", async () => {
    await expect(scraper()({ url: url("/captcha") })).rejects.toMatchObject({ code: "blocked" });
  });

  it("maps 5xx to fetch_failed and returns 404 pages with their status", async () => {
    await expect(scraper()({ url: url("/500") })).rejects.toMatchObject({ code: "fetch_failed" });
    expect((await scraper()({ url: url("/404") })).status).toBe(404);
  });

  it("rejects non-HTML and oversize bodies", async () => {
    await expect(scraper()({ url: url("/json") })).rejects.toMatchObject({ code: "fetch_failed" });
    await expect(scraper()({ url: url("/big") })).rejects.toMatchObject({ code: "fetch_failed" });
  });

  it("times out slow responses", async () => {
    await expect(scraper({ timeoutMs: 100 })({ url: url("/slow") })).rejects.toMatchObject({ code: "timeout" });
  });
});

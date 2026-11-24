import http from "node:http";
import https from "node:https";
import { ScrapeError } from "./errors";
import {
  DEFAULT_ALLOWED_PORTS,
  assertSafeUrl,
  isBlockedIp,
  pinnedLookup,
  resolveAndValidate,
  systemResolver,
  type IpPolicy,
  type Resolver,
} from "./ssrf";

export interface ScrapeHtmlResult {
  html: string;
  finalUrl: string;
  status: number;
  tier: "static";
}

export interface FetcherDeps {
  resolve: Resolver;
  /** Returns true if connecting to this IP is allowed. Production uses `!isBlockedIp`. */
  isAllowedIp: IpPolicy;
  allowedPorts: readonly number[];
  timeoutMs: number;
  maxBytes: number;
  maxRedirects: number;
  userAgent: string;
}

// TODO(next): make the contact URL configurable via env.
const DEFAULT_UA = "AIProductScraperBot/0.1 (+https://example.com/bot; respects robots.txt)";

export const DEFAULT_FETCHER_DEPS: FetcherDeps = {
  resolve: systemResolver,
  isAllowedIp: (ip) => !isBlockedIp(ip),
  allowedPorts: DEFAULT_ALLOWED_PORTS,
  timeoutMs: 15_000,
  maxBytes: 2 * 1024 * 1024,
  maxRedirects: 5,
  userAgent: DEFAULT_UA,
};

const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);
// Specific vendor markers only; the bare word "captcha" would match ordinary pages.
const CHALLENGE_MARKERS = /g-recaptcha|h-captcha|cf-turnstile|cf-challenge|challenge-platform|captcha-delivery/i;

interface RawResponse {
  status: number;
  headers: http.IncomingHttpHeaders;
  body: string;
}

function requestOnce(url: URL, deps: FetcherDeps, pinned: Parameters<typeof pinnedLookup>[0]): Promise<RawResponse> {
  return new Promise((resolve, reject) => {
    const client = url.protocol === "https:" ? https : http;
    const req = client.request(
      {
        protocol: url.protocol,
        hostname: url.hostname.replace(/^\[|\]$/g, ""), // Host header and TLS SNI stay the original name
        port: url.port || undefined,
        path: `${url.pathname}${url.search}`,
        method: "GET",
        // No Accept-Encoding: identity responses only, so no decompression bombs.
        headers: { "user-agent": deps.userAgent, accept: "text/html,application/xhtml+xml" },
        lookup: pinnedLookup(pinned),
      },
      (res) => {
        const status = res.statusCode ?? 0;
        if (REDIRECT_STATUSES.has(status)) {
          res.destroy();
          resolve({ status, headers: res.headers, body: "" });
          return;
        }
        const chunks: Buffer[] = [];
        let size = 0;
        res.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > deps.maxBytes) {
            req.destroy();
            reject(new ScrapeError("fetch_failed", "response exceeds size cap", { status }));
            return;
          }
          chunks.push(chunk);
        });
        res.on("end", () =>
          resolve({ status, headers: res.headers, body: new TextDecoder("utf-8").decode(Buffer.concat(chunks)) }),
        );
        res.on("error", () => reject(new ScrapeError("fetch_failed", "response stream error", { status })));
      },
    );
    req.setTimeout(deps.timeoutMs, () => {
      req.destroy();
      reject(new ScrapeError("timeout", "request timed out"));
    });
    req.on("error", (err) => {
      reject(err instanceof ScrapeError ? err : new ScrapeError("fetch_failed", "connection failed"));
    });
    req.end();
  });
}

function parseRetryAfter(value: string | undefined): number | undefined {
  if (!value) return undefined;
  const secs = Number(value);
  if (Number.isFinite(secs)) return secs;
  const date = Date.parse(value);
  return Number.isNaN(date) ? undefined : Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

export function createScrapeHtml(overrides: Partial<FetcherDeps> = {}) {
  const deps: FetcherDeps = { ...DEFAULT_FETCHER_DEPS, ...overrides };

  return async function scrapeHtml({ url }: { url: string }): Promise<ScrapeHtmlResult> {
    let current = assertSafeUrl(url, deps.allowedPorts);

    for (let hop = 0; hop <= deps.maxRedirects; hop++) {
      // Every hop (including the first) is re-validated and re-pinned.
      const pinned = await resolveAndValidate(current.hostname, deps.resolve, deps.isAllowedIp);
      const res = await requestOnce(current, deps, pinned);

      if (REDIRECT_STATUSES.has(res.status)) {
        const location = res.headers.location;
        if (!location) throw new ScrapeError("fetch_failed", "redirect without Location", { status: res.status });
        let next: URL;
        try {
          next = new URL(location, current);
        } catch {
          throw new ScrapeError("fetch_failed", "invalid redirect target", { status: res.status });
        }
        current = assertSafeUrl(next, deps.allowedPorts);
        continue;
      }

      // Never retry or work around these: stop and report.
      if (res.status === 401 || res.status === 403 || res.status === 429) {
        throw new ScrapeError("blocked", `access refused (HTTP ${res.status})`, {
          status: res.status,
          retryAfterSeconds: parseRetryAfter(res.headers["retry-after"]),
        });
      }
      if (res.status >= 500) throw new ScrapeError("fetch_failed", `server error (HTTP ${res.status})`, { status: res.status });

      const type = res.headers["content-type"] ?? "";
      if (type && !/html|xml/i.test(type)) throw new ScrapeError("fetch_failed", "response is not HTML", { status: res.status });
      if (CHALLENGE_MARKERS.test(res.body)) throw new ScrapeError("blocked", "bot challenge detected", { status: res.status });

      return { html: res.body, finalUrl: current.toString(), status: res.status, tier: "static" };
    }
    throw new ScrapeError("fetch_failed", "too many redirects");
  };
}

// TODO(next): robots.txt, per-domain token bucket, circuit breaker, Redis cache and
// conditional GET, Playwright tier, and the egress proxy (phase 6).
export const scrapeHtml = createScrapeHtml();

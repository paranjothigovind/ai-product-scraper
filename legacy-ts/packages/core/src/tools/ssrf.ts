import { lookup as dnsLookup } from "node:dns/promises";
import { isIP } from "node:net";
import { ScrapeError } from "./errors";

export const DEFAULT_ALLOWED_PORTS: readonly number[] = [80, 443];

export interface ResolvedAddress {
  address: string;
  family: number;
}
export type Resolver = (hostname: string) => Promise<ResolvedAddress[]>;
export type IpPolicy = (ip: string) => boolean;

export const systemResolver: Resolver = (hostname) => dnsLookup(hostname, { all: true, verbatim: true });

// [network, prefix length]
const BLOCKED_V4: readonly (readonly [string, number])[] = [
  ["0.0.0.0", 8],
  ["10.0.0.0", 8],
  ["100.64.0.0", 10], // carrier-grade NAT
  ["127.0.0.0", 8],
  ["169.254.0.0", 16], // link-local + cloud metadata
  ["172.16.0.0", 12],
  ["192.0.0.0", 24],
  ["192.0.2.0", 24],
  ["192.168.0.0", 16],
  ["198.18.0.0", 15],
  ["198.51.100.0", 24],
  ["203.0.113.0", 24],
  ["224.0.0.0", 4],
  ["240.0.0.0", 4],
];

function v4ToInt(ip: string): number | null {
  const parts = ip.split(".");
  if (parts.length !== 4) return null;
  let n = 0;
  for (const p of parts) {
    if (!/^\d{1,3}$/.test(p) || Number(p) > 255) return null;
    n = n * 256 + Number(p);
  }
  return n;
}

function isBlockedV4(ip: string): boolean {
  const n = v4ToInt(ip);
  if (n === null) return true;
  return BLOCKED_V4.some(([net, bits]) => {
    const base = v4ToInt(net);
    if (base === null) return true;
    const size = 2 ** (32 - bits);
    return Math.floor(n / size) === Math.floor(base / size);
  });
}

function parseV6(input: string): number[] | null {
  let s = input.split("%")[0] ?? "";
  if (s.includes(".")) {
    const idx = s.lastIndexOf(":");
    const octets = s.slice(idx + 1).split(".").map(Number);
    if (octets.length !== 4 || octets.some((o) => !Number.isInteger(o) || o < 0 || o > 255)) return null;
    const [a, b, c, d] = octets as [number, number, number, number];
    s = `${s.slice(0, idx + 1)}${((a << 8) | b).toString(16)}:${((c << 8) | d).toString(16)}`;
  }
  let groups: string[];
  if (s.includes("::")) {
    const [head = "", tail = ""] = s.split("::");
    const h = head ? head.split(":") : [];
    const t = tail ? tail.split(":") : [];
    const fill = 8 - h.length - t.length;
    if (fill < 1) return null;
    groups = [...h, ...Array<string>(fill).fill("0"), ...t];
  } else {
    groups = s.split(":");
  }
  if (groups.length !== 8) return null;
  const nums = groups.map((g) => (/^[0-9a-f]{1,4}$/i.test(g) ? parseInt(g, 16) : NaN));
  return nums.some(Number.isNaN) ? null : nums;
}

function embeddedV4(hi: number, lo: number): string {
  return `${hi >> 8}.${hi & 255}.${lo >> 8}.${lo & 255}`;
}

function isBlockedV6(ip: string): boolean {
  const g = parseV6(ip);
  if (!g) return true;
  const [g0, g1, g2, g3, g4, g5, g6, g7] = g as [number, number, number, number, number, number, number, number];
  if (g0 === 0 && g1 === 0 && g2 === 0 && g3 === 0 && g4 === 0) {
    if (g5 === 0xffff) return isBlockedV4(embeddedV4(g6, g7)); // IPv4-mapped
    return true; // ::, ::1 and deprecated IPv4-compatible
  }
  if (g0 === 0x64 && g1 === 0xff9b && g2 === 0 && g3 === 0 && g4 === 0 && g5 === 0) {
    return isBlockedV4(embeddedV4(g6, g7)); // NAT64
  }
  if (g0 === 0x2002) return isBlockedV4(embeddedV4(g1, g2)); // 6to4
  if ((g0 & 0xffc0) === 0xfe80) return true; // link-local
  if ((g0 & 0xfe00) === 0xfc00) return true; // unique local (includes fd00:ec2::254)
  if ((g0 & 0xff00) === 0xff00) return true; // multicast
  if (g0 === 0x2001 && g1 === 0x0db8) return true; // documentation
  if (g0 === 0x0100 && g1 === 0 && g2 === 0 && g3 === 0) return true; // discard prefix
  return false;
}

/** True when the address is private, loopback, link-local, metadata, reserved, or unparsable. */
export function isBlockedIp(ip: string): boolean {
  const family = isIP(ip);
  if (family === 4) return isBlockedV4(ip);
  if (family === 6) return isBlockedV6(ip);
  return true;
}

/** Validates scheme, credentials and port. Hostname checks happen after DNS resolution. */
export function assertSafeUrl(raw: string | URL, allowedPorts: readonly number[] = DEFAULT_ALLOWED_PORTS): URL {
  let url: URL;
  try {
    url = raw instanceof URL ? raw : new URL(raw);
  } catch {
    throw new ScrapeError("invalid_input", "invalid URL");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ScrapeError("invalid_input", `scheme not allowed: ${url.protocol}`);
  }
  if (url.username || url.password) throw new ScrapeError("invalid_input", "credentials in URL not allowed");
  if (!url.hostname) throw new ScrapeError("invalid_input", "missing host");
  if (url.port !== "" && !allowedPorts.includes(Number(url.port))) {
    throw new ScrapeError("invalid_input", `port not allowed: ${url.port}`);
  }
  return url;
}

/**
 * Resolves DNS ourselves and rejects if ANY returned address is blocked
 * (a mixed answer is a rebinding signal). Returns the one address to pin.
 */
export async function resolveAndValidate(
  hostname: string,
  resolve: Resolver,
  isAllowedIp: IpPolicy,
): Promise<ResolvedAddress> {
  const bare = hostname.replace(/^\[|\]$/g, "");
  let addrs: ResolvedAddress[];
  if (isIP(bare)) {
    addrs = [{ address: bare, family: isIP(bare) }];
  } else {
    try {
      addrs = await resolve(bare);
    } catch {
      throw new ScrapeError("fetch_failed", "DNS resolution failed");
    }
  }
  const first = addrs[0];
  if (!first) throw new ScrapeError("fetch_failed", "DNS returned no addresses");
  if (addrs.some((a) => !isAllowedIp(a.address))) {
    throw new ScrapeError("invalid_input", "host resolves to a blocked address");
  }
  return first;
}

/** A `lookup` for http(s).request that ignores DNS and always returns the validated IP. */
export function pinnedLookup(pinned: ResolvedAddress) {
  return (
    _hostname: string,
    options: { all?: boolean },
    cb: (err: Error | null, address: string | ResolvedAddress[], family?: number) => void,
  ): void => {
    if (options.all) cb(null, [pinned]);
    else cb(null, pinned.address, pinned.family);
  };
}

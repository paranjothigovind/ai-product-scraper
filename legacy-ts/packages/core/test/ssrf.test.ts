import { describe, expect, it } from "vitest";
import { ScrapeError } from "../src/tools/errors";
import { assertSafeUrl, isBlockedIp, pinnedLookup, resolveAndValidate } from "../src/tools/ssrf";
import { createScrapeHtml } from "../src/tools/scrape-html";

describe("isBlockedIp", () => {
  it.each([
    "127.0.0.1",
    "127.1.2.3",
    "10.0.0.5",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.1",
    "169.254.169.254", // cloud metadata
    "100.64.0.1",
    "0.0.0.0",
    "224.0.0.1",
    "255.255.255.255",
    "::1",
    "::",
    "fe80::1",
    "fc00::1",
    "fd00:ec2::254", // AWS IPv6 metadata
    "::ffff:127.0.0.1", // IPv4-mapped loopback
    "::ffff:7f00:1", // same, hex form
    "::ffff:169.254.169.254",
    "64:ff9b::7f00:1", // NAT64 to loopback
    "2002:7f00:1::", // 6to4 to loopback
    "ff02::1",
    "not-an-ip",
  ])("blocks %s", (ip) => {
    expect(isBlockedIp(ip)).toBe(true);
  });

  it.each(["8.8.8.8", "93.184.216.34", "172.32.0.1", "172.15.255.255", "2606:4700:4700::1111", "::ffff:8.8.8.8"])(
    "allows public %s",
    (ip) => {
      expect(isBlockedIp(ip)).toBe(false);
    },
  );
});

describe("assertSafeUrl", () => {
  it.each([
    "file:///etc/passwd",
    "ftp://example.com/",
    "gopher://example.com/",
    "javascript:alert(1)",
    "data:text/html,hi",
    "http://user:pass@example.com/",
    "http://example.com:8080/",
    "http://example.com:22/",
    "https://example.com:6379/",
    "not a url",
  ])("rejects %s", (u) => {
    expect(() => assertSafeUrl(u)).toThrow(ScrapeError);
  });

  it("accepts http/https on default and allowed ports", () => {
    expect(() => assertSafeUrl("http://example.com/")).not.toThrow();
    expect(() => assertSafeUrl("https://example.com:443/x")).not.toThrow();
    expect(() => assertSafeUrl("http://example.com:80/x")).not.toThrow();
  });

  it("normalizes obfuscated IP literals so the IP check sees them", () => {
    // WHATWG URL turns decimal/hex/octal forms into dotted quads.
    for (const u of ["http://2130706433/", "http://0x7f.1/", "http://017700000001/", "http://127.1/"]) {
      expect(isBlockedIp(assertSafeUrl(u).hostname)).toBe(true);
    }
  });
});

describe("resolveAndValidate", () => {
  const allow = (ip: string) => !isBlockedIp(ip);

  it("rejects a name that resolves to loopback or metadata", async () => {
    await expect(resolveAndValidate("evil.test", async () => [{ address: "127.0.0.1", family: 4 }], allow)).rejects.toThrow(/blocked/);
    await expect(resolveAndValidate("evil.test", async () => [{ address: "169.254.169.254", family: 4 }], allow)).rejects.toThrow(/blocked/);
  });

  it("rejects mixed public+private answers (rebinding signal)", async () => {
    const mixed = async () => [
      { address: "93.184.216.34", family: 4 },
      { address: "10.0.0.1", family: 4 },
    ];
    await expect(resolveAndValidate("evil.test", mixed, allow)).rejects.toThrow(/blocked/);
  });

  it("rejects IP literals without consulting DNS", async () => {
    const neverCalled = async () => {
      throw new Error("DNS must not be used");
    };
    await expect(resolveAndValidate("[::1]", neverCalled, allow)).rejects.toThrow(/blocked/);
    await expect(resolveAndValidate("127.0.0.1", neverCalled, allow)).rejects.toThrow(/blocked/);
  });

  it("returns the address to pin, and the pinned lookup ignores later DNS changes", async () => {
    let calls = 0;
    // First answer is public, any later answer would be loopback (classic rebinding).
    const rebinding = async () => (calls++ === 0 ? [{ address: "93.184.216.34", family: 4 }] : [{ address: "127.0.0.1", family: 4 }]);
    const pinned = await resolveAndValidate("rebind.test", rebinding, allow);
    expect(pinned.address).toBe("93.184.216.34");

    const results: string[] = [];
    pinnedLookup(pinned)("rebind.test", {}, (_e, address) => results.push(String(address)));
    pinnedLookup(pinned)("rebind.test", { all: true }, (_e, list) => results.push(JSON.stringify(list)));
    expect(results[0]).toBe("93.184.216.34");
    expect(results[1]).toContain("93.184.216.34");
    expect(calls).toBe(1);
  });
});

describe("default scrapeHtml rejects attacks before connecting", () => {
  const scrape = createScrapeHtml({
    resolve: async (h) => (h === "meta.test" ? [{ address: "169.254.169.254", family: 4 }] : [{ address: "127.0.0.1", family: 4 }]),
  });

  it.each([
    "file:///etc/passwd",
    "http://127.0.0.1/",
    "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/",
    "http://meta.test/",
    "http://localhost/",
    "http://example.com:8080/",
  ])("%s", async (url) => {
    await expect(scrape({ url })).rejects.toMatchObject({ code: "invalid_input" });
  });
});

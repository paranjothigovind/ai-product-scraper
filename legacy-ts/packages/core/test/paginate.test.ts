import { describe, expect, it } from "vitest";
import { paginate } from "../src/tools/paginate";
import { canonicalUrl } from "../src/tools/url";

const B = "https://shop.test/catalog/";

describe("paginate", () => {
  it("prefers link[rel=next]", () => {
    const html = `<head><link rel="next" href="?p=9"></head><a href="/other">next</a>`;
    expect(paginate({ html, currentUrl: B })).toEqual({ nextUrl: "https://shop.test/catalog/?p=9", strategy: "rel_next" });
  });

  it("finds a Next anchor (books.toscrape style)", () => {
    const html = `<ul><li class="next"><a href="page-2.html">next</a></li></ul>`;
    expect(paginate({ html, currentUrl: "https://shop.test/catalogue/page-1.html" })).toEqual({
      nextUrl: "https://shop.test/catalogue/page-2.html",
      strategy: "next_anchor",
    });
  });

  it("recognizes the › glyph and ignores disabled next buttons", () => {
    expect(paginate({ html: `<a href="/c?x=2">›</a>`, currentUrl: B }).strategy).toBe("next_anchor");
    expect(paginate({ html: `<li class="disabled"><a href="/c?x=2">Next</a></li>`, currentUrl: B }).nextUrl).toBeNull();
  });

  it("increments ?page=N and /page/N/", () => {
    expect(paginate({ html: "<p/>", currentUrl: "https://shop.test/c?page=3" })).toEqual({
      nextUrl: "https://shop.test/c?page=4",
      strategy: "page_param",
    });
    expect(paginate({ html: "<p/>", currentUrl: "https://shop.test/c/page/2/" })).toEqual({
      nextUrl: "https://shop.test/c/page/3/",
      strategy: "page_path",
    });
  });

  it("follows a page-2 link seen on the first page, but does not guess otherwise", () => {
    expect(paginate({ html: `<a href="/c?page=2">2</a>`, currentUrl: "https://shop.test/c" }).nextUrl).toBe("https://shop.test/c?page=2");
    expect(paginate({ html: "<p>one page</p>", currentUrl: "https://shop.test/c" })).toEqual({ nextUrl: null, strategy: "none" });
  });

  it("returns null for an already-visited URL instead of falling through", () => {
    const visited = new Set(["https://shop.test/c?page=2"]);
    const html = `<link rel="next" href="/c?page=2">`;
    expect(paginate({ html, currentUrl: "https://shop.test/c?page=1", visited }).nextUrl).toBeNull();
  });

  it("never leaves the host", () => {
    expect(paginate({ html: `<link rel="next" href="https://evil.test/c?page=2">`, currentUrl: B }).nextUrl).toBeNull();
  });
});

describe("canonicalUrl", () => {
  it("strips fragments, tracking params and sorts the query", () => {
    expect(canonicalUrl("/p?b=2&utm_source=x&a=1#top", "https://s.test/")).toBe("https://s.test/p?a=1&b=2");
  });
  it("rejects non-http schemes", () => {
    expect(canonicalUrl("javascript:alert(1)")).toBeNull();
    expect(canonicalUrl("file:///etc/passwd")).toBeNull();
  });
});

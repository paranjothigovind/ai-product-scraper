import { describe, expect, it } from "vitest";
import { parsePrice, validateProducts } from "../src/tools/validate-products";

const base = "https://shop.test/list/";
const item = (o: Record<string, unknown> = {}) => ({ name: "Widget", url: "/p/1", price: "$10.00", source: "selector", ...o });

describe("parsePrice", () => {
  it.each([
    ["$1,299.00", 1299, "USD"],
    ["£12.50", 12.5, "GBP"],
    ["1.299,00 €", 1299, "EUR"],
    ["12,50", 12.5, null],
    ["1,299", 1299, null],
    [49, 49, null],
  ])("%s", (input, price, currency) => {
    expect(parsePrice(input)).toEqual({ price, currency });
  });
  it("returns null for garbage", () => {
    expect(parsePrice("call us").price).toBeNull();
    expect(parsePrice(undefined).price).toBeNull();
  });
});

describe("validateProducts", () => {
  it("resolves relative URLs, normalizes price, and infers currency", () => {
    const { valid } = validateProducts({ products: [item({ image: "../img/a.png" })], baseUrl: base });
    expect(valid[0]).toMatchObject({ url: "https://shop.test/p/1", price: 10, currency: "USD", image: "https://shop.test/img/a.png" });
  });

  it("drops items without a name or usable url and reports why", () => {
    const { valid, invalid } = validateProducts({
      products: [item({ name: "  " }), item({ url: "javascript:x" }), item({ url: undefined }), "junk", item()],
      baseUrl: base,
    });
    expect(valid).toHaveLength(1);
    expect(invalid.map((i) => i.reason)).toEqual(["missing name", "missing or invalid url", "missing or invalid url", "malformed product"]);
  });

  it("clamps rating to 0-5 and normalizes availability", () => {
    const { valid } = validateProducts({
      products: [item({ rating: 9 }), item({ url: "/p/2", name: "B", rating: -1, availability: "https://schema.org/OutOfStock" })],
      baseUrl: base,
    });
    expect(valid[0]?.rating).toBe(5);
    expect(valid[1]).toMatchObject({ rating: 0, availability: "out_of_stock" });
  });

  it("dedupes by canonical url, then by name+price", () => {
    const { valid, duplicates } = validateProducts({
      products: [
        item(),
        item({ url: "/p/1?utm_source=x#frag" }), // same canonical URL
        item({ url: "/p/other", name: "widget" }), // same name+price, different URL
        item({ url: "/p/3", name: "Widget", price: "$11" }), // different price: kept
      ],
      baseUrl: base,
    });
    expect(valid.map((p) => p.url)).toEqual(["https://shop.test/p/1", "https://shop.test/p/3"]);
    expect(duplicates).toBe(2);
  });

  it("keeps null price when unknown and generates a stable id", () => {
    const a = validateProducts({ products: [item({ price: undefined })], baseUrl: base }).valid[0];
    const b = validateProducts({ products: [item({ price: undefined })], baseUrl: base }).valid[0];
    expect(a?.price).toBeNull();
    expect(a?.id).toBe(b?.id);
  });
});

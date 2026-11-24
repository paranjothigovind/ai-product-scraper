import { describe, expect, it } from "vitest";
import { createScrapeInputSchema } from "../src/schemas/input";
import { Product } from "../src/schemas/product";

const Input = createScrapeInputSchema(500);

describe("ScrapeInput", () => {
  it("accepts a url and applies defaults", () => {
    const r = Input.parse({ url: "https://books.toscrape.com/", maxProducts: 20 });
    expect(r.scope).toBe("category");
    expect(r.maxDepth).toBe(2);
  });

  it("rejects both or neither of url/html", () => {
    expect(Input.safeParse({ maxProducts: 5 }).success).toBe(false);
    expect(Input.safeParse({ url: "https://a.com", html: "<p/>", maxProducts: 5 }).success).toBe(false);
  });

  it("enforces maxProducts bounds and the plan cap", () => {
    expect(Input.safeParse({ url: "https://a.com", maxProducts: 0 }).success).toBe(false);
    expect(Input.safeParse({ url: "https://a.com", maxProducts: 501 }).success).toBe(false);
    expect(Input.safeParse({ url: "https://a.com", maxProducts: 500 }).success).toBe(true);
  });

  it("rejects non-http schemes and oversize inputs", () => {
    expect(Input.safeParse({ url: "file:///etc/passwd", maxProducts: 1 }).success).toBe(false);
    expect(Input.safeParse({ url: `https://a.com/${"x".repeat(2048)}`, maxProducts: 1 }).success).toBe(false);
    expect(Input.safeParse({ html: "x".repeat(1_000_001), maxProducts: 1 }).success).toBe(false);
  });

  it("rejects unknown keys", () => {
    expect(Input.safeParse({ url: "https://a.com", maxProducts: 1, extra: 1 }).success).toBe(false);
  });
});

describe("Product", () => {
  const base = {
    id: "1",
    name: "A Book",
    url: "https://a.com/p/1",
    price: 10,
    currency: "GBP",
    image: null,
    brand: null,
    category: null,
    rating: 4,
    reviewCount: 3,
    availability: "in_stock",
    description: null,
    source: "jsonld",
  };

  it("accepts a valid product", () => {
    expect(Product.safeParse(base).success).toBe(true);
  });

  it("rejects relative urls and out-of-range rating", () => {
    expect(Product.safeParse({ ...base, url: "/p/1" }).success).toBe(false);
    expect(Product.safeParse({ ...base, rating: 6 }).success).toBe(false);
  });
});

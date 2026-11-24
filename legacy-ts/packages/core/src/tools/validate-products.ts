import { createHash } from "node:crypto";
import { z } from "zod";
import { Product, ProductSource } from "../schemas/product";
import { canonicalUrl } from "./url";

const CURRENCY_SYMBOLS: Record<string, string> = { $: "USD", "£": "GBP", "€": "EUR", "₹": "INR" };

/** "$1,299.00" -> 1299, "1.299,00 €" -> 1299, "12,50" -> 12.5. Null when unparsable. */
export function parsePrice(value: unknown): { price: number | null; currency: string | null } {
  if (typeof value === "number") return { price: Number.isFinite(value) ? value : null, currency: null };
  if (typeof value !== "string") return { price: null, currency: null };
  const symbol = Object.keys(CURRENCY_SYMBOLS).find((s) => value.includes(s));
  const digits = value.replace(/[^\d.,]/g, "");
  if (!/\d/.test(digits)) return { price: null, currency: null };
  const lastDot = digits.lastIndexOf(".");
  const lastComma = digits.lastIndexOf(",");
  let normalized: string;
  if (lastDot >= 0 && lastComma >= 0) {
    const decimalSep = lastDot > lastComma ? "." : ",";
    normalized = digits.split(decimalSep === "." ? "," : ".").join("").replace(decimalSep, ".");
  } else if (lastComma >= 0) {
    // "12,50" is a decimal comma; "1,299" is a thousands separator.
    normalized = /,\d{1,2}$/.test(digits) && digits.indexOf(",") === lastComma ? digits.replace(",", ".") : digits.replace(/,/g, "");
  } else {
    normalized = digits;
  }
  const price = Number(normalized);
  return {
    price: Number.isFinite(price) ? price : null,
    currency: symbol ? (CURRENCY_SYMBOLS[symbol] ?? null) : null,
  };
}

function parseAvailability(value: unknown): Product["availability"] {
  if (typeof value !== "string") return "unknown";
  const v = value.toLowerCase().replace(/[^a-z]/g, "");
  if (/outofstock|soldout|unavailable|discontinued/.test(v)) return "out_of_stock";
  if (/instock|available|limitedavailability|onlineonly/.test(v)) return "in_stock";
  return "unknown";
}

const text = (v: unknown): string | null => {
  if (typeof v !== "string") return null;
  const t = v.replace(/\s+/g, " ").trim();
  return t === "" ? null : t;
};

const numberOrNull = (v: unknown): number | null => {
  const n = typeof v === "string" ? Number(v.replace(/[^\d.]/g, "")) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
};

const RawProduct = z.object({
  id: z.unknown().optional(),
  name: z.unknown(),
  url: z.unknown(),
  price: z.unknown().optional(),
  currency: z.unknown().optional(),
  image: z.unknown().optional(),
  brand: z.unknown().optional(),
  category: z.unknown().optional(),
  rating: z.unknown().optional(),
  reviewCount: z.unknown().optional(),
  availability: z.unknown().optional(),
  description: z.unknown().optional(),
  source: ProductSource,
});

export interface InvalidProduct {
  input: unknown;
  reason: string;
}

export function dedupeProducts(products: readonly Product[]): Product[] {
  const seenUrl = new Set<string>();
  const seenNamePrice = new Set<string>();
  const out: Product[] = [];
  for (const p of products) {
    const url = canonicalUrl(p.url) ?? p.url;
    const namePrice = `${p.name.toLowerCase()}|${p.price ?? ""}`;
    if (seenUrl.has(url) || seenNamePrice.has(namePrice)) continue;
    seenUrl.add(url);
    seenNamePrice.add(namePrice);
    out.push(p);
  }
  return out;
}

export function validateProducts({
  products,
  baseUrl,
}: {
  products: readonly unknown[];
  /** Used to resolve relative product and image URLs. */
  baseUrl?: string;
}): { valid: Product[]; invalid: InvalidProduct[]; duplicates: number } {
  const normalized: Product[] = [];
  const invalid: InvalidProduct[] = [];

  for (const input of products) {
    const raw = RawProduct.safeParse(input);
    if (!raw.success) {
      invalid.push({ input, reason: "malformed product" });
      continue;
    }
    const r = raw.data;
    const name = text(r.name);
    if (!name) {
      invalid.push({ input, reason: "missing name" });
      continue;
    }
    const url = typeof r.url === "string" ? canonicalUrl(r.url, baseUrl) : null;
    if (!url) {
      invalid.push({ input, reason: "missing or invalid url" });
      continue;
    }
    const { price, currency: symbolCurrency } = parsePrice(r.price);
    const image = typeof r.image === "string" ? canonicalUrl(r.image, baseUrl) : null;
    const rating = numberOrNull(r.rating);
    const reviewCount = numberOrNull(r.reviewCount);

    const candidate = {
      id: text(r.id) ?? createHash("sha1").update(url).digest("hex").slice(0, 16),
      name,
      url,
      price: price !== null && price >= 0 ? price : null,
      currency: text(r.currency)?.toUpperCase() ?? symbolCurrency,
      image,
      brand: text(r.brand),
      category: text(r.category),
      rating: rating === null ? null : Math.min(5, Math.max(0, rating)),
      reviewCount: reviewCount === null ? null : Math.max(0, Math.round(reviewCount)),
      availability: parseAvailability(r.availability),
      description: text(r.description),
      source: r.source,
    };
    const parsed = Product.safeParse(candidate);
    if (parsed.success) normalized.push(parsed.data);
    else invalid.push({ input, reason: parsed.error.issues.map((i) => i.path.join(".")).join(",") });
  }

  const valid = dedupeProducts(normalized);
  return { valid, invalid, duplicates: normalized.length - valid.length };
}

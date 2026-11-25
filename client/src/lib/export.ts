import type { Product } from "./types";

const COLUMNS = [
  "rank",
  "name",
  "url",
  "price",
  "currency",
  "image",
  "brand",
  "category",
  "rating",
  "review_count",
  "availability",
  "source",
] as const;

/** A cell that starts with = + - @ is run as a formula by spreadsheets; neutralise it. */
function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text = String(value);
  if (typeof value === "string" && /^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(products: readonly Product[]): string {
  const rows = products.map((p) => COLUMNS.map((c) => cell(p[c])).join(","));
  return [COLUMNS.join(","), ...rows].join("\r\n");
}

export function toJson(products: readonly Product[]): string {
  return JSON.stringify(products, null, 2);
}

export function download(filename: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** Only ever link to web URLs, whatever a scraped page claimed. */
export function safeHref(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export function formatPrice(price: number | null, currency: string | null): string {
  if (price === null) return "—";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency ?? "USD",
    }).format(price);
  } catch {
    return `${price.toFixed(2)}${currency ? ` ${currency}` : ""}`;
  }
}

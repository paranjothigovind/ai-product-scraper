import { download, formatPrice, safeHref, toCsv, toJson } from "@/lib/export";
import type { Product } from "@/lib/types";
import { ProductImage } from "./product-image";

const AVAILABILITY: Record<Product["availability"], string> = {
  in_stock: "In stock",
  out_of_stock: "Out of stock",
  unknown: "",
};

const SOURCE: Record<Product["source"], string> = {
  jsonld: "structured data",
  microdata: "structured data",
  selector: "page markup",
  llm: "AI",
};

export function Results({ products }: { products: Product[] }) {
  if (products.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-neutral-300 p-8 text-center text-sm text-neutral-600 dark:border-neutral-700 dark:text-neutral-400">
        No products were found.
      </p>
    );
  }

  return (
    <section aria-label="Results" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">
          {products.length} {products.length === 1 ? "product" : "products"}, best first
        </h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => download("products.csv", toCsv(products), "text/csv;charset=utf-8")}
            className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm font-medium hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
          >
            Download CSV
          </button>
          <button
            type="button"
            onClick={() => download("products.json", toJson(products), "application/json")}
            className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm font-medium hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
          >
            Download JSON
          </button>
        </div>
      </div>

      <ol className="divide-y divide-neutral-200 rounded-xl border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
        {products.map((p) => (
          <ProductRow key={p.id} product={p} />
        ))}
      </ol>
    </section>
  );
}

function ProductRow({ product: p }: { product: Product }) {
  const href = safeHref(p.url);
  const image = safeHref(p.image);
  const availability = AVAILABILITY[p.availability];

  return (
    <li className="flex gap-4 p-4">
      <span className="w-6 shrink-0 pt-1 text-right text-sm tabular-nums text-neutral-500">
        {p.rank ?? "–"}
      </span>
      <ProductImage src={image} />
      <div className="min-w-0 flex-1">
        <h3 className="truncate font-medium">
          {href ? (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="hover:underline"
            >
              {p.name}
            </a>
          ) : (
            p.name
          )}
        </h3>
        <p className="mt-0.5 text-sm text-neutral-600 dark:text-neutral-400">
          {[p.brand, p.category].filter(Boolean).join(" · ")}
        </p>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span className="font-semibold">{formatPrice(p.price, p.currency)}</span>
          {p.rating !== null && (
            <span>
              ★ {p.rating.toFixed(1)}
              {p.review_count !== null && (
                <span className="text-neutral-500"> ({p.review_count.toLocaleString()})</span>
              )}
            </span>
          )}
          {availability && <span className="text-neutral-600 dark:text-neutral-400">{availability}</span>}
          <span className="text-xs text-neutral-500">from {SOURCE[p.source]}</span>
        </p>
        {p.reason && <p className="mt-1 text-xs text-neutral-500">{p.reason}</p>}
      </div>
    </li>
  );
}

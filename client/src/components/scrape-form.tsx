"use client";

import { useState, type FormEvent } from "react";
import type { ScrapeInput } from "@/lib/types";

const MAX_HTML_BYTES = 1_000_000;

type Mode = "url" | "html";
type Errors = Partial<Record<"url" | "html" | "max_products" | "max_pages" | "max_depth", string>>;

const field =
  "w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm shadow-sm outline-none " +
  "focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 disabled:opacity-60 " +
  "dark:border-neutral-700 dark:bg-neutral-900";

function toInt(value: string): number | null {
  return /^\d+$/.test(value.trim()) ? Number(value) : null;
}

export function ScrapeForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (input: ScrapeInput) => void;
  disabled: boolean;
}) {
  const [mode, setMode] = useState<Mode>("url");
  const [url, setUrl] = useState("");
  const [html, setHtml] = useState("");
  const [maxProducts, setMaxProducts] = useState("20");
  const [scope, setScope] = useState<"site" | "category">("site");
  const [maxPages, setMaxPages] = useState("");
  const [maxDepth, setMaxDepth] = useState("2");
  const [errors, setErrors] = useState<Errors>({});

  function validate(): ScrapeInput | null {
    const next: Errors = {};
    const input: Partial<ScrapeInput> = { scope };

    if (mode === "url") {
      try {
        const parsed = new URL(url.trim());
        if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error();
        input.url = parsed.href;
      } catch {
        next.url = "Enter a full web address, like https://shop.example.com/products";
      }
    } else if (!html.trim()) {
      next.html = "Paste the page's HTML.";
    } else if (new TextEncoder().encode(html).length > MAX_HTML_BYTES) {
      next.html = "That HTML is over the 1 MB limit.";
    } else {
      input.html = html;
    }

    const products = toInt(maxProducts);
    if (products === null || products < 1) next.max_products = "Enter a whole number, 1 or more.";
    else input.max_products = products;

    if (maxPages.trim()) {
      const pages = toInt(maxPages);
      if (pages === null || pages < 1) next.max_pages = "Enter a whole number, 1 or more.";
      else input.max_pages = pages;
    }

    const depth = toInt(maxDepth);
    if (depth === null || depth > 5) next.max_depth = "Enter a number from 0 to 5.";
    else input.max_depth = depth;

    setErrors(next);
    return Object.keys(next).length ? null : (input as ScrapeInput);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const input = validate();
    if (input) onSubmit(input);
  }

  const err = (key: keyof Errors) =>
    errors[key] ? (
      <p id={`${key}-error`} role="alert" className="mt-1 text-sm text-red-600 dark:text-red-400">
        {errors[key]}
      </p>
    ) : null;

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <div role="radiogroup" aria-label="Where to scrape" className="inline-flex rounded-lg border border-neutral-300 p-1 dark:border-neutral-700">
        {(["url", "html"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={mode === m}
            disabled={disabled}
            onClick={() => setMode(m)}
            className={
              "rounded-md px-4 py-1.5 text-sm font-medium transition " +
              (mode === m
                ? "bg-blue-600 text-white"
                : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800")
            }
          >
            {m === "url" ? "Web address" : "Paste HTML"}
          </button>
        ))}
      </div>

      {mode === "url" ? (
        <div>
          <label htmlFor="url" className="mb-1 block text-sm font-medium">
            Page to scrape
          </label>
          <input
            id="url"
            type="url"
            inputMode="url"
            autoComplete="off"
            placeholder="https://shop.example.com/products"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={disabled}
            aria-invalid={Boolean(errors.url)}
            aria-describedby={errors.url ? "url-error" : undefined}
            className={field}
          />
          {err("url")}
        </div>
      ) : (
        <div>
          <label htmlFor="html" className="mb-1 block text-sm font-medium">
            Page HTML
          </label>
          <textarea
            id="html"
            rows={8}
            spellCheck={false}
            placeholder="<html>…</html>"
            value={html}
            onChange={(e) => setHtml(e.target.value)}
            disabled={disabled}
            aria-invalid={Boolean(errors.html)}
            aria-describedby={errors.html ? "html-error" : undefined}
            className={`${field} font-mono`}
          />
          {err("html")}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="max_products" className="mb-1 block text-sm font-medium">
            How many products
          </label>
          <input
            id="max_products"
            inputMode="numeric"
            value={maxProducts}
            onChange={(e) => setMaxProducts(e.target.value)}
            disabled={disabled}
            aria-invalid={Boolean(errors.max_products)}
            aria-describedby={errors.max_products ? "max_products-error" : undefined}
            className={field}
          />
          {err("max_products")}
        </div>
        <div>
          <label htmlFor="scope" className="mb-1 block text-sm font-medium">
            Scope
          </label>
          <select
            id="scope"
            value={scope}
            onChange={(e) => setScope(e.target.value as "site" | "category")}
            disabled={disabled}
            className={field}
          >
            <option value="site">Whole site</option>
            <option value="category">This category only</option>
          </select>
        </div>
      </div>

      <details className="rounded-lg border border-neutral-200 px-4 py-3 dark:border-neutral-800">
        <summary className="cursor-pointer text-sm font-medium">Advanced limits</summary>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="max_pages" className="mb-1 block text-sm font-medium">
              Max pages to fetch
            </label>
            <input
              id="max_pages"
              inputMode="numeric"
              placeholder="No extra limit"
              value={maxPages}
              onChange={(e) => setMaxPages(e.target.value)}
              disabled={disabled}
              aria-invalid={Boolean(errors.max_pages)}
              aria-describedby={errors.max_pages ? "max_pages-error" : undefined}
              className={field}
            />
            {err("max_pages")}
          </div>
          <div>
            <label htmlFor="max_depth" className="mb-1 block text-sm font-medium">
              Link depth (0–5)
            </label>
            <input
              id="max_depth"
              inputMode="numeric"
              value={maxDepth}
              onChange={(e) => setMaxDepth(e.target.value)}
              disabled={disabled}
              aria-invalid={Boolean(errors.max_depth)}
              aria-describedby={errors.max_depth ? "max_depth-error" : undefined}
              className={field}
            />
            {err("max_depth")}
          </div>
        </div>
      </details>

      <button
        type="submit"
        disabled={disabled}
        className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {disabled ? "Working…" : "Start scraping"}
      </button>
    </form>
  );
}

export type RunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "low_confidence"
  | "cancelled";

export const TERMINAL: readonly RunStatus[] = ["succeeded", "failed", "low_confidence", "cancelled"];

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL.includes(status);
}

export interface Product {
  id: string;
  rank: number | null;
  score: number | null;
  reason: string | null;
  name: string;
  url: string;
  price: number | null;
  currency: string | null;
  image: string | null;
  brand: string | null;
  category: string | null;
  rating: number | null;
  review_count: number | null;
  availability: "in_stock" | "out_of_stock" | "unknown";
  description: string | null;
  source: "jsonld" | "microdata" | "selector" | "llm";
}

export interface Category {
  name: string;
  slug: string;
  url: string | null;
  parent: string | null;
  product_count: number | null;
}

export interface Run {
  id: string;
  status: RunStatus;
  input_type: "url" | "html";
  source_url: string | null;
  requested: number;
  score: number | null;
  confidence: "high" | "medium" | "low" | null;
  pages_fetched: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  error_code: string | null;
  incomplete_reason: string | null;
  cancel_requested: boolean;
  created_at: string;
  finished_at: string | null;
  products: Product[] | null;
  categories: Category[] | null;
}

export interface ScrapeInput {
  url?: string;
  html?: string;
  max_products: number;
  scope: "site" | "category";
  max_pages?: number;
  max_depth?: number;
}

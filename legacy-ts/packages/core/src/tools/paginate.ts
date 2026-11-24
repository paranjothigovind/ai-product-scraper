import * as cheerio from "cheerio";
import { canonicalUrl } from "./url";

export type PaginateStrategy = "rel_next" | "next_anchor" | "page_param" | "page_path" | "none";
export interface PaginateResult {
  nextUrl: string | null;
  strategy: PaginateStrategy;
}

const NEXT_TEXT = /^(next( page)?|›|»|>|→)(\s*[›»>→])?$/i;

/**
 * Deterministic next-page detection. The first strategy that finds a candidate decides:
 * if that candidate was already visited we return null instead of trying weaker strategies,
 * which is what stops pagination loops.
 */
export function paginate({
  html,
  currentUrl,
  visited = new Set<string>(),
}: {
  html: string;
  currentUrl: string;
  visited?: ReadonlySet<string>;
}): PaginateResult {
  const current = canonicalUrl(currentUrl);
  if (!current) return { nextUrl: null, strategy: "none" };
  const host = new URL(current).hostname;
  const $ = cheerio.load(html);

  const decide = (href: string | undefined, strategy: PaginateStrategy): PaginateResult | null => {
    if (!href) return null;
    const candidate = canonicalUrl(href, current);
    if (!candidate || candidate === current || new URL(candidate).hostname !== host) return null;
    return { nextUrl: visited.has(candidate) ? null : candidate, strategy };
  };

  const relNext = decide($("link[rel~=next], a[rel~=next]").first().attr("href"), "rel_next");
  if (relNext) return relNext;

  const anchor = $("a[href]")
    .filter((_, el) => {
      const a = $(el);
      if (a.closest(".disabled, [aria-disabled=true]").length) return false;
      const label = (a.attr("aria-label") ?? a.attr("title") ?? "").trim();
      return NEXT_TEXT.test(a.text().trim()) || /^next( page)?$/i.test(label);
    })
    .first();
  const nextAnchor = decide(anchor.attr("href"), "next_anchor");
  if (nextAnchor) return nextAnchor;

  // Blind increment applies only when the current URL already carries a page number.
  const currentUrlObj = new URL(current);
  const pageParam = currentUrlObj.searchParams.get("page");
  if (pageParam !== null && /^\d+$/.test(pageParam)) {
    currentUrlObj.searchParams.set("page", String(Number(pageParam) + 1));
    return decide(currentUrlObj.toString(), "page_param") ?? { nextUrl: null, strategy: "none" };
  }
  const pathMatch = /\/page\/(\d+)(\/?)$/.exec(currentUrlObj.pathname);
  if (pathMatch) {
    currentUrlObj.pathname = currentUrlObj.pathname.replace(
      /\/page\/\d+(\/?)$/,
      `/page/${Number(pathMatch[1]) + 1}$1`,
    );
    return decide(currentUrlObj.toString(), "page_path") ?? { nextUrl: null, strategy: "none" };
  }

  // First page of a listing: follow a link to page 2 only if the page itself shows one.
  for (const el of $("a[href]").toArray()) {
    const href = $(el).attr("href");
    const candidate = href ? canonicalUrl(href, current) : null;
    if (!candidate) continue;
    const u = new URL(candidate);
    if (u.hostname !== host) continue;
    if (u.pathname === currentUrlObj.pathname && u.searchParams.get("page") === "2") return decide(candidate, "page_param") ?? { nextUrl: null, strategy: "none" };
    if (u.pathname === `${currentUrlObj.pathname.replace(/\/$/, "")}/page/2/` || u.pathname === `${currentUrlObj.pathname.replace(/\/$/, "")}/page/2`) {
      return decide(candidate, "page_path") ?? { nextUrl: null, strategy: "none" };
    }
  }
  return { nextUrl: null, strategy: "none" };
}

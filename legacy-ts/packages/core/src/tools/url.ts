const NOISE_PARAM = /^(utm_.*|fbclid|gclid|msclkid|mc_.*|sessionid|phpsessid|jsessionid|sid|ref)$/i;

/** Absolute, fragment-free, noise-free URL with sorted query. Null if not a valid http(s) URL. */
export function canonicalUrl(raw: string, base?: string): string | null {
  let url: URL;
  try {
    url = new URL(raw.trim(), base);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  url.hash = "";
  url.pathname = url.pathname.replace(/;jsessionid=[^/?]*/i, "");
  for (const key of [...url.searchParams.keys()]) {
    if (NOISE_PARAM.test(key)) url.searchParams.delete(key);
  }
  url.searchParams.sort();
  return url.toString();
}

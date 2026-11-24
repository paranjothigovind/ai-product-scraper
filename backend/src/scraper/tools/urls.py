import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

_NOISE_PARAM = re.compile(
    r"^(utm_.*|fbclid|gclid|msclkid|mc_.*|sessionid|phpsessid|jsessionid|sid|ref)$", re.I
)
_JSESSION = re.compile(r";jsessionid=[^/?]*", re.I)
_DEFAULT_PORT = {"http": 80, "https": 443}


def canonical_url(raw: str, base: str | None = None) -> str | None:
    """Absolute, fragment-free URL with tracking/session noise removed and a sorted query.
    None when the result is not a plain http(s) URL."""
    try:
        parts = urlsplit(urljoin(base or "", raw.strip()))
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORT or not host:
        return None
    bracketed = f"[{host}]" if ":" in host else host
    netloc = bracketed if port in (None, _DEFAULT_PORT[scheme]) else f"{bracketed}:{port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _NOISE_PARAM.match(k)
    )
    path = _JSESSION.sub("", parts.path) or "/"
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def same_site(host_a: str | None, host_b: str | None) -> bool:
    """Same host ignoring a leading www. TODO(next): real registrable-domain check (needs a
    public-suffix list, which the dependency rules do not allow yet)."""
    if not host_a or not host_b:
        return False
    return host_a.lower().removeprefix("www.") == host_b.lower().removeprefix("www.")

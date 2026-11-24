import re
from collections.abc import Set
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

from scraper.html.dom import Node, parse_html
from scraper.tools.urls import canonical_url, same_site

Strategy = Literal["rel_next", "next_anchor", "page_param", "page_path", "none"]
_NEXT_TEXT = re.compile(r"^(next( page)?|›|»|>|→)(\s*[›»>→])?$", re.I)  # noqa: RUF001
_NEXT_LABEL = re.compile(r"^next( page)?$", re.I)
_PAGE_PATH = re.compile(r"/page/(\d+)(/?)$")


class PageLink(BaseModel):
    next_url: str | None
    strategy: Strategy


def _is_disabled(anchor: Node) -> bool:
    for node in (anchor, *anchor.ancestors()):
        if not node.is_element:
            continue
        if "disabled" in node.classes or node.attrs.get("aria-disabled", "").lower() == "true":
            return True
    return False


def _with_query(url: str, query: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def paginate(html: str, current_url: str, visited: Set[str] = frozenset()) -> PageLink:
    """Deterministic next-page detection. The first strategy that finds a candidate decides: if
    that candidate was already visited the result is None rather than a weaker guess, which is
    what stops pagination loops."""
    current = canonical_url(current_url)
    if current is None:
        return PageLink(next_url=None, strategy="none")
    host = urlsplit(current).hostname
    root = parse_html(html).root

    def decide(href: str | None, strategy: Strategy) -> PageLink | None:
        if not href:
            return None
        candidate = canonical_url(href, current)
        if (
            candidate is None
            or candidate == current
            or not same_site(urlsplit(candidate).hostname, host)
        ):
            return None
        return PageLink(next_url=None if candidate in visited else candidate, strategy=strategy)

    for link in root.elements():
        rel = link.attrs.get("rel", "").lower().split()
        if (
            link.tag in ("link", "a")
            and "next" in rel
            and (hit := decide(link.get("href"), "rel_next"))
        ):
            return hit

    anchors = [a for a in root.elements("a") if a.attrs.get("href") and not _is_disabled(a)]
    for a in anchors:
        label = (a.attrs.get("aria-label") or a.attrs.get("title") or "").strip()
        text = " ".join(a.text_content().split())
        if (_NEXT_TEXT.match(text) or _NEXT_LABEL.match(label)) and (
            hit := decide(a.get("href"), "next_anchor")
        ):
            return hit

    parts = urlsplit(current)
    # A blind increment is only safe when the current URL already carries a page number.
    params = [kv.split("=", 1) for kv in parts.query.split("&") if kv]
    for i, kv in enumerate(params):
        if kv[0] == "page" and len(kv) == 2 and kv[1].isdigit():
            params[i] = ["page", str(int(kv[1]) + 1)]
            query = "&".join("=".join(p) for p in params)
            return decide(_with_query(current, query), "page_param") or PageLink(
                next_url=None, strategy="none"
            )
    if m := _PAGE_PATH.search(parts.path):
        path = _PAGE_PATH.sub(f"/page/{int(m.group(1)) + 1}{m.group(2)}", parts.path)
        bumped = urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))
        return decide(bumped, "page_path") or PageLink(next_url=None, strategy="none")

    # First page of a listing: follow a page-2 link only if the page itself shows one.
    base_path = parts.path.rstrip("/")
    for a in anchors:
        candidate = canonical_url(a.attrs["href"], current)
        if candidate is None:
            continue
        cparts = urlsplit(candidate)
        if not same_site(cparts.hostname, host):
            continue
        if cparts.path == parts.path and "page=2" in cparts.query.split("&"):
            return decide(candidate, "page_param") or PageLink(next_url=None, strategy="none")
        if cparts.path.rstrip("/") == f"{base_path}/page/2":
            return decide(candidate, "page_path") or PageLink(next_url=None, strategy="none")
    return PageLink(next_url=None, strategy="none")

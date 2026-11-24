"""Visible-text extraction. This is the only text that reaches an LLM, so anything a human
would not see (hidden elements, scripts, comments) is dropped here."""

import re
from urllib.parse import urljoin, urlparse

from scraper.html.dom import TEXT, Node

# Content never rendered as page text.
SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "template", "head", "iframe", "object", "embed", "canvas"}
    | {"svg", "math"}
)
_BLOCK_TAGS = frozenset(
    {"address", "article", "aside", "blockquote", "br", "dd", "details", "div", "dl", "dt"}
    | {"fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6"}
    | {"header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tr", "ul"}
    | {"td", "th", "option"}
)

_WS = re.compile(r"\s+")
_ZERO = re.compile(r"^[+-]?0*\.?0+(px|em|rem|%|pt|vh|vw)?$")
_OFFSCREEN = re.compile(r"^-(\d+(?:\.\d+)?)(px|em|rem|vw|%)?$")


def _parse_style(style: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for declaration in style.split(";"):
        name, sep, value = declaration.partition(":")
        if sep:
            props[name.strip().lower()] = value.replace("!important", "").strip().lower()
    return props


def _is_zero(value: str | None) -> bool:
    return value is not None and _ZERO.match(value) is not None


def _is_offscreen(value: str | None) -> bool:
    match = _OFFSCREEN.match(value) if value else None
    if not match:
        return False
    magnitude, unit = float(match.group(1)), match.group(2)
    return magnitude >= (100 if unit in ("em", "rem") else 1000)


def style_hides(style: str) -> bool:
    p = _parse_style(style)
    if p.get("display") == "none" or p.get("visibility") in ("hidden", "collapse"):
        return True
    if _is_zero(p.get("opacity")) or _is_zero(p.get("font-size")):
        return True
    if p.get("color") == "transparent":
        return True
    clipped = p.get("overflow") == "hidden"
    zero_w = _is_zero(p.get("width")) or _is_zero(p.get("max-width"))
    zero_h = _is_zero(p.get("height")) or _is_zero(p.get("max-height"))
    if (zero_w and zero_h) or (clipped and (zero_w or zero_h)):
        return True
    return any(_is_offscreen(p.get(k)) for k in ("left", "top", "text-indent", "margin-left"))


def is_hidden(node: Node) -> bool:
    """Static check only: CSS classes and stylesheets are not evaluated."""
    if not node.is_element:
        return False
    attrs = node.attrs
    if "hidden" in attrs or attrs.get("aria-hidden", "").strip().lower() == "true":
        return True
    if node.tag == "input" and attrs.get("type", "").lower() == "hidden":
        return True
    style = attrs.get("style")
    return style is not None and style_hides(style)


def _link(href: str | None, base_url: str | None) -> str | None:
    if not href or href.startswith("#"):
        return None
    absolute = urljoin(base_url or "", href.strip())
    return absolute if urlparse(absolute).scheme in ("http", "https") else None


def render_text(root: Node, *, base_url: str | None = None, include_links: bool = True) -> str:
    """Visible text, one block per line. Links render as `text [absolute-url]` so the model
    can see product URLs without ever seeing markup."""
    out: list[str] = []
    stack: list[tuple[Node, bool]] = [(root, False)]  # (node, is_exit)
    while stack:
        node, is_exit = stack.pop()
        if node.tag == TEXT:
            # Source newlines are not line breaks in HTML; only block boundaries are.
            out.append(_WS.sub(" ", node.text))
            continue
        if is_exit:
            if node.tag == "a" and include_links:
                url = _link(node.attrs.get("href"), base_url)
                if url:
                    out.append(f" [{url}] ")
            if node.tag in _BLOCK_TAGS:
                out.append("\n")
            continue
        if node.is_element and (node.tag in SKIP_TAGS or is_hidden(node)):
            continue
        if node.tag in _BLOCK_TAGS:
            out.append("\n")
        stack.append((node, True))
        stack.extend((child, False) for child in reversed(node.children))
    lines = (" ".join(line.split()) for line in "".join(out).split("\n"))
    return "\n".join(line for line in lines if line)

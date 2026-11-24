"""A deliberately minimal selector engine: tag, #id, .class, [attr], [attr=value], descendant
(space) and child (>) combinators. Nothing else, so LLM-proposed selectors can be validated
by simply failing to compile."""

import re
from functools import lru_cache
from typing import Literal, NamedTuple

from scraper.html.dom import Node

MAX_SELECTOR_CHARS = 500
MAX_COMPOUNDS = 10

_TAG = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
_IDENT = re.compile(r"[A-Za-z_][\w-]*")
_ATTR = re.compile(
    r"""\[\s*([A-Za-z_:][\w:.-]*)\s*(?:=\s*(?:"([^"]*)"|'([^']*)'|([^\]\s"']+)))?\s*\]"""
)


class SelectorError(ValueError):
    pass


class Compound(NamedTuple):
    tag: str | None
    ids: tuple[str, ...]
    classes: tuple[str, ...]
    attrs: tuple[tuple[str, str | None], ...]


class Part(NamedTuple):
    # How this compound relates to the previous one; None for the first.
    combinator: Literal["descendant", "child"] | None
    compound: Compound


def _parse_compound(s: str, i: int) -> tuple[Compound, int]:
    tag: str | None = None
    ids: list[str] = []
    classes: list[str] = []
    attrs: list[tuple[str, str | None]] = []
    if m := _TAG.match(s, i):
        tag, i = m.group().lower(), m.end()
    while i < len(s):
        c = s[i]
        if c in "#.":
            m = _IDENT.match(s, i + 1)
            if not m:
                raise SelectorError(f"expected identifier at {i + 1}")
            (ids if c == "#" else classes).append(m.group())
            i = m.end()
        elif c == "[":
            m = _ATTR.match(s, i)
            if not m:
                raise SelectorError(f"bad attribute selector at {i}")
            value = next((g for g in m.groups()[1:] if g is not None), None)
            attrs.append((m.group(1).lower(), value))
            i = m.end()
        else:
            break
    if tag is None and not (ids or classes or attrs):
        raise SelectorError(f"unsupported or empty selector at {i}")
    return Compound(tag, tuple(ids), tuple(classes), tuple(attrs)), i


@lru_cache(maxsize=512)
def compile_selector(selector: str) -> tuple[Part, ...]:
    s = selector.strip()
    if not s or len(s) > MAX_SELECTOR_CHARS:
        raise SelectorError("empty or too long")
    parts: list[Part] = []
    combinator: Literal["descendant", "child"] | None = None
    i = 0
    while i < len(s):
        compound, i = _parse_compound(s, i)
        parts.append(Part(combinator, compound))
        if len(parts) > MAX_COMPOUNDS:
            raise SelectorError("too many compounds")
        had_space = i < len(s) and s[i].isspace()
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s):
            break
        if s[i] == ">":
            combinator = "child"
            i += 1
            while i < len(s) and s[i].isspace():
                i += 1
            if i >= len(s):
                raise SelectorError("dangling combinator")
        elif had_space:
            combinator = "descendant"
        else:
            raise SelectorError(f"unsupported syntax at {i}: {s[i]!r}")
    return tuple(parts)


def _matches_compound(node: Node, c: Compound) -> bool:
    if not node.is_element or (c.tag is not None and node.tag != c.tag):
        return False
    attrs = node.attrs
    if any(attrs.get("id") != i for i in c.ids):
        return False
    if c.classes and not set(c.classes) <= node.classes:
        return False
    return all(n in attrs and (v is None or attrs[n] == v) for n, v in c.attrs)


def _matches(node: Node, parts: tuple[Part, ...]) -> bool:
    # Right-to-left; memoized so descendant chains stay O(depth * parts) on deep pages.
    memo: dict[tuple[int, int], bool] = {}

    def match(n: Node, i: int) -> bool:
        key = (id(n), i)
        if key in memo:
            return memo[key]
        ok = _matches_compound(n, parts[i].compound)
        if ok and i > 0:
            if parts[i].combinator == "child":
                ok = n.parent is not None and match(n.parent, i - 1)
            else:
                ok = any(match(a, i - 1) for a in n.ancestors())
        memo[key] = ok
        return ok

    return match(node, len(parts) - 1)


def select(root: Node, selector: str) -> list[Node]:
    """Descendants of `root` matching `selector`, in document order. Ancestors above `root`
    may satisfy earlier compounds, as with querySelectorAll."""
    parts = compile_selector(selector)
    return [n for n in root.elements() if _matches(n, parts)]


def select_one(root: Node, selector: str) -> Node | None:
    parts = compile_selector(selector)
    return next((n for n in root.elements() if _matches(n, parts)), None)

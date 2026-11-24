"""Maps schema.org nodes (from JSON-LD or microdata, both normalized to nested dicts) onto our
Product and Category models."""

import hashlib
import re
from collections.abc import Iterable
from html import unescape
from typing import Literal
from urllib.parse import urldefrag, urljoin, urlparse

from pydantic import BaseModel, Field, ValidationError

from scraper.html.values import (
    collapse_ws,
    parse_availability,
    parse_price,
    slugify,
    to_float,
    to_int,
)
from scraper.schemas.product import Category, Product

Node = dict[str, object]

MAX_NODES = 100_000
MAX_DEPTH = 32
_PRODUCT_TYPES = frozenset({"Product", "IndividualProduct", "SomeProducts", "ProductModel"})
# Related-product links are not products on this page; reviews point back at the same product.
_SKIP_KEYS = frozenset(
    {"isRelatedTo", "isSimilarTo", "isAccessoryOrSparePartFor", "isConsumableFor", "review"}
    | {"itemReviewed", "successorOf", "predecessorOf", "mainEntityOfPage", "isVariantOf"}
)


class SchemaOrgResult(BaseModel):
    products: list[Product] = Field(default_factory=list)
    categories: list[Category] = Field(default_factory=list)
    # Bare product URLs from ItemLists that carry no other data.
    item_urls: list[str] = Field(default_factory=list)
    dropped: int = 0


def _as_node(value: object) -> Node | None:
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return value
    return None


def _walk(roots: Iterable[object]) -> list[Node]:
    found: list[Node] = []
    stack: list[tuple[object, int]] = [(r, 0) for r in reversed(list(roots))]
    visited = 0
    while stack and visited < MAX_NODES:
        obj, depth = stack.pop()
        visited += 1
        if depth > MAX_DEPTH:
            continue
        if isinstance(obj, list):
            stack.extend((item, depth + 1) for item in reversed(obj))
        elif (node := _as_node(obj)) is not None:
            found.append(node)
            stack.extend(
                (v, depth + 1)
                for k, v in reversed(list(node.items()))
                if k not in _SKIP_KEYS and isinstance(v, dict | list)
            )
    return found


def _types(node: Node) -> set[str]:
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return {re.split(r"[/#:]", v)[-1] for v in values if isinstance(v, str)}


def _deref(value: object, index: dict[str, Node]) -> object:
    node = _as_node(value)
    if node is not None and len(node) == 1 and isinstance(node.get("@id"), str):
        return index.get(str(node["@id"]), value)
    return value


def _first(value: object, index: dict[str, Node]) -> object:
    value = _deref(value, index)
    if isinstance(value, list):
        return _deref(value[0], index) if value else None
    return value


def _str(value: object, limit: int = 2000) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value")
    if isinstance(value, int | float) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    text = collapse_ws(value)[:limit]
    return text or None


def _absolute(value: object, base_url: str | None) -> str | None:
    text = _str(value, 2048)
    if text is None:
        return None
    url = urldefrag(urljoin(base_url or "", text)).url
    return url if urlparse(url).scheme in ("http", "https") and urlparse(url).netloc else None


def _node_url(value: object, base_url: str | None, index: dict[str, Node]) -> str | None:
    value = _first(value, index)
    node = _as_node(value)
    if node is not None:
        return _absolute(node.get("url") or node.get("@id"), base_url)
    return _absolute(value, base_url)


def _strip_tags(text: str) -> str:
    # Tags first, then entities, so an escaped "&lt;b&gt;" stays literal text.
    return collapse_ws(unescape(re.sub(r"<[^>]+>", " ", text)))


def _pick_offer(value: object, index: dict[str, Node]) -> Node | None:
    value = _deref(value, index)
    candidates = value if isinstance(value, list) else [value]
    offers = [o for c in candidates if (o := _as_node(_deref(c, index))) is not None]
    for offer in offers:
        if any(k in offer for k in ("price", "lowPrice", "priceSpecification")):
            return offer
    return offers[0] if offers else None


def _candidate(
    node: Node,
    *,
    base_url: str | None,
    fallback_url: str | None,
    index: dict[str, Node],
    source: Literal["jsonld", "microdata"],
) -> dict[str, object] | None:
    name = _str(_first(node.get("name"), index), 500)
    if name is None:
        return None
    offer = _pick_offer(node.get("offers"), index)
    url = (
        _absolute(node.get("url"), base_url)
        or (_absolute(offer.get("url"), base_url) if offer else None)
        or _absolute(node.get("@id"), base_url)
        or fallback_url
    )
    if url is None:
        return None

    price: float | None = None
    currency: str | None = None
    availability = "unknown"
    if offer is not None:
        spec = _as_node(_first(offer.get("priceSpecification"), index)) or {}
        raw_price = next(
            (v for v in (offer.get("price"), offer.get("lowPrice"), spec.get("price")) if v),
            offer.get("price"),
        )
        price, symbol_currency = parse_price(raw_price)
        currency = (_str(offer.get("priceCurrency")) or symbol_currency or "").upper() or None
        availability = parse_availability(_str(offer.get("availability")))
    if price is not None and price < 0:
        price = None

    rating: float | None = None
    review_count: int | None = None
    agg = _as_node(_first(node.get("aggregateRating"), index))
    if agg is not None:
        value = to_float(agg.get("ratingValue"))
        best = to_float(agg.get("bestRating")) or 5.0
        if value is not None:
            rating = min(5.0, max(0.0, value / best * 5.0))
        review_count = to_int(agg.get("reviewCount") or agg.get("ratingCount"))

    return {
        "id": hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:16],
        "name": name,
        "url": url,
        "price": price,
        "currency": currency,
        "image": _node_url(node.get("image"), base_url, index),
        "brand": _str(_first(node.get("brand"), index), 200),
        "category": _str(_first(node.get("category"), index), 200),
        "rating": rating,
        "review_count": review_count,
        "availability": availability,
        "description": _strip_tags(d)[:2000] if (d := _str(node.get("description"))) else None,
        "source": source,
    }


def _is_product(node: Node) -> bool:
    types = _types(node)
    if types & _PRODUCT_TYPES:
        # A ProductGroup is represented by its variants, so only plain products qualify here.
        return True
    return "offers" in node and "name" in node


def _list_items(node: Node, index: dict[str, Node]) -> list[Node]:
    raw = _deref(node.get("itemListElement"), index)
    items = raw if isinstance(raw, list) else [raw]
    nodes = [n for i in items if (n := _as_node(_deref(i, index))) is not None]
    if nodes and all(isinstance(n.get("position"), int | float | str) for n in nodes):
        nodes.sort(key=lambda n: to_float(n.get("position")) or 0.0)
    return nodes


def _crumbs(
    node: Node, base_url: str | None, index: dict[str, Node]
) -> list[tuple[str, str | None]]:
    crumbs: list[tuple[str, str | None]] = []
    for item in _list_items(node, index):
        inner = _first(item.get("item"), index)
        inner_node = _as_node(inner)
        name = _str(item.get("name")) or (inner_node and _str(inner_node.get("name")))
        if name:
            url = _node_url(item.get("item") or item.get("url"), base_url, index)
            crumbs.append((name, url))
    return crumbs


def map_nodes(
    roots: Iterable[object],
    *,
    base_url: str | None,
    source: Literal["jsonld", "microdata"],
) -> SchemaOrgResult:
    nodes = _walk(roots)
    index = {str(n["@id"]): n for n in nodes if isinstance(n.get("@id"), str) and len(n) > 1}
    result = SchemaOrgResult()

    product_nodes = [n for n in nodes if _is_product(n) and "hasVariant" not in n]
    # A lone Product with no URL of its own is the page's subject: the page URL identifies it.
    fallback = base_url if len(product_nodes) == 1 else None
    candidates = [
        c
        for n in product_nodes
        if (
            c := _candidate(n, base_url=base_url, fallback_url=fallback, index=index, source=source)
        )
        is not None
    ]
    result.dropped += len(product_nodes) - len(candidates)

    for node in nodes:
        types = _types(node)
        if "ItemList" in types:
            for item in _list_items(node, index):
                inner = _first(item.get("item"), index)
                if isinstance(inner, str):
                    if url := _absolute(inner, base_url):
                        result.item_urls.append(url)
                    continue
                target = _as_node(inner) or item
                if _is_product(target):
                    continue  # already collected through the walk
                if (name := _str(target.get("name"))) and (
                    url := _absolute(target.get("url") or item.get("url"), base_url)
                ):
                    candidates.append(
                        {
                            "id": hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[
                                :16
                            ],
                            "name": name,
                            "url": url,
                            "source": source,
                        }
                    )
                elif url := _absolute(target.get("url") or item.get("url"), base_url):
                    result.item_urls.append(url)
        elif "BreadcrumbList" in types:
            crumbs = _crumbs(node, base_url, index)
            product_names = {c["name"] for c in candidates}
            # The last crumb is usually the current page; on a product page that is the product.
            if crumbs and crumbs[-1][0] in product_names:
                crumbs = crumbs[:-1]
            if len(crumbs) > 1 and (crumbs[0][0].lower() == "home" or _is_root(crumbs[0][1])):
                crumbs = crumbs[1:]
                parent: str | None = None
            else:
                parent = None
            for name, url in crumbs:
                result.categories.append(
                    Category(name=name, slug=slugify(name) or "category", url=url, parent=parent)
                )
                parent = name

    for cand in candidates:
        try:
            result.products.append(Product.model_validate(cand))
        except ValidationError:
            result.dropped += 1

    seen = {c.slug for c in result.categories}
    for product in result.products:
        if product.category and (slug := slugify(product.category)) and slug not in seen:
            seen.add(slug)
            result.categories.append(Category(name=product.category, slug=slug))
    return result


def _is_root(url: str | None) -> bool:
    return url is not None and urlparse(url).path in ("", "/")

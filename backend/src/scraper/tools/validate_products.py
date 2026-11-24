import hashlib
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field, ValidationError

from scraper.html.values import collapse_ws, parse_availability, parse_price, to_float, to_int
from scraper.schemas.product import Product
from scraper.tools.urls import canonical_url


class InvalidProduct(BaseModel):
    input: dict[str, object]
    errors: list[str]


class ValidationResult(BaseModel):
    valid: list[Product] = Field(default_factory=list)
    invalid: list[InvalidProduct] = Field(default_factory=list)
    duplicates: int = 0


def _text(value: object, limit: int = 2000) -> str | None:
    if not isinstance(value, str):
        return None
    text = collapse_ws(value)[:limit]
    return text or None


def _normalize(raw: Mapping[str, object], base_url: str | None) -> dict[str, object] | list[str]:
    """Returns a candidate dict for Product, or a list of problems."""
    problems: list[str] = []
    name = _text(raw.get("name"), 500)
    if name is None:
        problems.append("name: missing")
    raw_url = raw.get("url")
    url = canonical_url(raw_url, base_url) if isinstance(raw_url, str) else None
    if url is None:
        problems.append("url: missing or not a valid http(s) URL")
    if raw.get("source") not in ("jsonld", "microdata", "selector", "llm"):
        problems.append("source: missing or unknown")
    if problems or name is None or url is None:
        return problems

    price, symbol_currency = parse_price(raw.get("price"))
    rating = to_float(raw.get("rating"))
    review_count = to_int(raw.get("review_count"))
    raw_image = raw.get("image")
    currency = _text(raw.get("currency"), 8)
    return {
        # Derived from the URL, never trusted from the source, so ids are stable across runs.
        "id": hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:16],
        "name": name,
        "url": url,
        "price": price if price is not None and price >= 0 else None,
        "currency": currency.upper() if currency else symbol_currency,
        "image": canonical_url(raw_image, base_url) if isinstance(raw_image, str) else None,
        "brand": _text(raw.get("brand"), 200),
        "category": _text(raw.get("category"), 200),
        "rating": None if rating is None else min(5.0, max(0.0, rating)),
        "review_count": review_count,
        "availability": parse_availability(raw.get("availability")),
        "description": _text(raw.get("description")),
        "source": raw["source"],
    }


def dedupe_products(products: Sequence[Product]) -> list[Product]:
    """First occurrence wins: by canonical URL, then by case-insensitive name + price."""
    seen_urls: set[str] = set()
    seen_name_price: set[tuple[str, float | None]] = set()
    unique: list[Product] = []
    for p in products:
        url = canonical_url(str(p.url)) or str(p.url)
        name_price = (p.name.lower(), p.price)
        if url in seen_urls or name_price in seen_name_price:
            continue
        seen_urls.add(url)
        seen_name_price.add(name_price)
        unique.append(p)
    return unique


def validate_products(
    products: Sequence[Product | Mapping[str, object]], base_url: str | None = None
) -> ValidationResult:
    result = ValidationResult()
    normalized: list[Product] = []
    for item in products:
        raw = item.model_dump(mode="json") if isinstance(item, Product) else dict(item)
        candidate = _normalize(raw, base_url)
        if isinstance(candidate, list):
            result.invalid.append(InvalidProduct(input=raw, errors=candidate))
            continue
        try:
            normalized.append(Product.model_validate(candidate))
        except ValidationError as exc:
            errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
            result.invalid.append(InvalidProduct(input=raw, errors=errors))
    result.valid = dedupe_products(normalized)
    result.duplicates = len(normalized) - len(result.valid)
    return result

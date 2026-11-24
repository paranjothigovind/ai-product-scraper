from typing import Any

import pytest
from pydantic import ValidationError

from scraper.schemas import Product, ScrapeRequest

CAP = {"plan_cap": 500}


def req(**kw: Any) -> ScrapeRequest:
    return ScrapeRequest.model_validate(kw, context=CAP)


def test_accepts_url_and_applies_defaults() -> None:
    r = req(url="https://books.toscrape.com/", max_products=20)
    assert r.scope == "site"
    assert r.max_depth == 2


@pytest.mark.parametrize(
    "data",
    [
        {"max_products": 5},
        {"url": "https://a.com", "html": "<p/>", "max_products": 5},
    ],
)
def test_requires_exactly_one_of_url_or_html(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        req(**data)


def test_max_products_bounds_and_plan_cap() -> None:
    with pytest.raises(ValidationError):
        req(url="https://a.com", max_products=0)
    with pytest.raises(ValidationError, match="plan cap"):
        req(url="https://a.com", max_products=501)
    assert req(url="https://a.com", max_products=500).max_products == 500


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://a.com/", "javascript:alert(1)"])
def test_rejects_non_http_schemes(url: str) -> None:
    with pytest.raises(ValidationError):
        req(url=url, max_products=1)


def test_rejects_oversize_url_and_html() -> None:
    with pytest.raises(ValidationError):
        req(url="https://a.com/" + "x" * 2048, max_products=1)
    with pytest.raises(ValidationError):
        req(html="x" * 1_000_001, max_products=1)


def test_html_limit_counts_bytes_not_characters() -> None:
    # 400k characters, 1.2M bytes.
    with pytest.raises(ValidationError):
        req(html="€" * 400_000, max_products=1)


def test_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        req(url="https://a.com", max_products=1, extra=1)


PRODUCT: dict[str, Any] = {
    "id": "1",
    "name": "A Book",
    "url": "https://a.com/p/1",
    "price": 10,
    "source": "jsonld",
}


def test_product_defaults_and_validation() -> None:
    p = Product.model_validate(PRODUCT)
    assert p.availability == "unknown"
    assert p.rating is None


@pytest.mark.parametrize("patch", [{"url": "/p/1"}, {"rating": 6}, {"price": -1}, {"name": ""}])
def test_product_rejects_bad_values(patch: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Product.model_validate({**PRODUCT, **patch})

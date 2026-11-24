from scraper.tools.paginate import PageLink, paginate
from scraper.tools.scrape_html import FetchContext, FetchResult, scrape_html
from scraper.tools.urls import canonical_url
from scraper.tools.validate_products import (
    ValidationResult,
    dedupe_products,
    validate_products,
)

__all__ = [
    "FetchContext",
    "FetchResult",
    "PageLink",
    "ValidationResult",
    "canonical_url",
    "dedupe_products",
    "paginate",
    "scrape_html",
    "validate_products",
]

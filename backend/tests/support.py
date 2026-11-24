"""Test doubles for the graph: a scripted site, an in-memory store, and a controllable clock."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from scraper.core.errors import ScrapeError
from scraper.graph.records import PageRecord, RunOutcome, TraceRecord
from scraper.schemas.error_code import ErrorCode
from scraper.schemas.eval import EvalReport
from scraper.schemas.product import Category, RankedProduct
from scraper.tools.scrape_html import FetchResult

BASE = "https://shop.test"


def product_ld(i: int, **extra: Any) -> dict[str, Any]:
    return {
        "@type": "Product",
        "name": f"Widget number {i}",
        "url": f"/p/{i}",
        "image": f"/img/{i}.jpg",
        "brand": "Acme",
        "offers": {"price": 10 + i, "priceCurrency": "USD", "availability": "InStock"},
        "aggregateRating": {"ratingValue": 4, "reviewCount": 10 + i},
    } | extra


def listing(products: Sequence[int], next_url: str | None = None) -> str:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps(product_ld(i))}</script>' for i in products
    )
    nxt = f'<link rel="next" href="{next_url}">' if next_url else ""
    return f"<html><head>{nxt}</head><body>{blocks}<p>listing</p></body></html>"


class ScriptedSite:
    """Serves pages by URL and records every fetch. A page may be an HTML string or an exception
    instance to raise."""

    def __init__(self, pages: Mapping[str, str | Exception]) -> None:
        self.pages = dict(pages)
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            raise ScrapeError(ErrorCode.FETCH_FAILED, "not found", status=404)
        if isinstance(page, Exception):
            raise page
        return FetchResult(
            html=page, final_url=url, status=200, bytes_read=len(page), duration_ms=1
        )


def paged_site(per_page: Sequence[Sequence[int]]) -> ScriptedSite:
    """/list, /list?page=2, ... each linking to the next."""
    pages: dict[str, str] = {}
    for n, ids in enumerate(per_page, start=1):
        url = f"{BASE}/list" if n == 1 else f"{BASE}/list?page={n}"
        nxt = f"{BASE}/list?page={n + 1}" if n < len(per_page) else None
        pages[url] = listing(ids, nxt)
    return ScriptedSite(pages)


class MemoryStore:
    """Mimics PostgresStore's upsert semantics so tests can assert nothing is duplicated."""

    def __init__(self) -> None:
        self.products: dict[tuple[str, str], RankedProduct] = {}
        self.categories: dict[tuple[str, str], Category] = {}
        self.pages: dict[tuple[str, int], PageRecord] = {}
        self.trace: dict[tuple[str, int], TraceRecord] = {}
        self.evals: dict[tuple[str, int], EvalReport] = {}
        self.outcomes: dict[str, RunOutcome] = {}
        self.persist_calls = 0
        self.finalize_calls = 0

    async def persist(
        self,
        run_id: str,
        *,
        products: Sequence[RankedProduct],
        categories: Sequence[Category],
        evaluation: EvalReport,
        attempt: int,
        trace: Sequence[TraceRecord],
        pages: Sequence[PageRecord],
    ) -> None:
        self.persist_calls += 1
        for key in [k for k in self.products if k[0] == run_id]:
            del self.products[key]
        for p in products:
            self.products[(run_id, str(p.url))] = p
        for c in categories:
            self.categories[(run_id, c.slug)] = c
        for page in pages:
            self.pages[(run_id, page.page_no)] = page
        for seq, t in enumerate(trace):
            self.trace[(run_id, seq)] = t
        self.evals[(run_id, attempt)] = evaluation

    async def finalize(self, run_id: str, outcome: RunOutcome) -> None:
        self.finalize_calls += 1
        self.outcomes[run_id] = outcome


class Cancel:
    def __init__(self, after_checks: int | None = None) -> None:
        self.checks = 0
        self.after = after_checks

    async def is_cancelled(self, run_id: str) -> bool:
        self.checks += 1
        return self.after is not None and self.checks > self.after


class Crash(Exception):
    """Simulates the worker process dying mid-run (not a ScrapeError, so nodes do not catch it)."""


class Flaky(ScriptedSite):
    def __init__(self, pages: Mapping[str, str | Exception], crash_on: str) -> None:
        super().__init__(pages)
        self.crash_on = crash_on
        self.crashed = False

    async def fetch(self, url: str) -> FetchResult:
        if url == self.crash_on and not self.crashed:
            self.calls.append(url)
            self.crashed = True
            raise Crash("worker died")
        return await super().fetch(url)

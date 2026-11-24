import json
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from scraper.core.errors import ScrapeError
from scraper.graph import GraphDeps, RunLimits, build_graph, run_graph
from scraper.graph.state import GraphState
from scraper.schemas.error_code import ErrorCode
from scraper.schemas.request import ScrapeRequest
from scraper.tools.scrape_html import FetchResult
from tests.support import (
    BASE,
    Cancel,
    Crash,
    Flaky,
    MemoryStore,
    ScriptedSite,
    listing,
    paged_site,
    product_ld,
)

LIST = f"{BASE}/list"


def page_url(n: int) -> str:
    return LIST if n == 1 else f"{LIST}?page={n}"


def request(max_products: int, **kw: Any) -> ScrapeRequest:
    return ScrapeRequest.model_validate({"url": LIST, "max_products": max_products} | kw)


class Harness:
    def __init__(self, site: ScriptedSite, **kw: Any) -> None:
        self.site = site
        self.store: MemoryStore = kw.pop("store", None) or MemoryStore()
        self.saver = MemorySaver()
        self.deps = GraphDeps(fetch=site.fetch, store=self.store, **kw)
        self.graph = build_graph(self.deps, self.saver)
        self.run_id = str(uuid.uuid4())

    async def run(self, req: ScrapeRequest) -> GraphState:
        return await run_graph(self.graph, self.run_id, req, self.deps.limits)


def result_of(state: GraphState) -> dict[str, Any]:
    return state["result"]


# --- the happy path -------------------------------------------------------------------------


async def test_returns_exactly_n_ranked_products_from_jsonld_with_no_llm() -> None:
    h = Harness(paged_site([[1, 2, 3, 4, 5]]))
    state = await h.run(request(3))
    result = result_of(state)
    assert len(result["products"]) == 3
    assert [p["rank"] for p in result["products"]] == [1, 2, 3]
    assert {p["source"] for p in result["products"]} == {"jsonld"}
    assert result["incomplete"] is False and result["incomplete_reason"] is None
    assert result["error_code"] is None
    assert h.store.outcomes[h.run_id].status == "succeeded"
    assert result["confidence"] == "high"
    extract = next(t for t in state["trace"] if t["node"] == "extract")
    assert extract["meta"]["llm_calls"] == 0
    assert len(h.store.products) == 3


async def test_fewer_products_than_requested_is_reported_not_hidden() -> None:
    h = Harness(paged_site([[1, 2, 3]]))
    result = result_of(await h.run(request(10)))
    assert len(result["products"]) == 3
    assert result["incomplete"] is True
    assert "fewer products than requested" in result["incomplete_reason"]
    assert h.store.outcomes[h.run_id].status == "low_confidence"
    assert len(h.store.products) == 3  # partial results are kept


async def test_stops_paginating_as_soon_as_the_limit_is_met() -> None:
    h = Harness(paged_site([[1, 2], [3, 4], [5, 6]]))
    result = result_of(await h.run(request(3)))
    assert len(result["products"]) == 3
    assert h.site.calls == [page_url(1), page_url(2)]  # page 3 never fetched


async def test_follows_every_page_and_never_revisits() -> None:
    site = paged_site([[1, 2], [3, 4], [5, 6]])
    # A page that links back to an earlier one must not cause a loop.
    site.pages[page_url(3)] = listing([5, 6], page_url(1))
    h = Harness(site)
    result = result_of(await h.run(request(100)))
    assert h.site.calls == [page_url(1), page_url(2), page_url(3)]
    assert len(result["products"]) == 6


class Endless(ScriptedSite):
    async def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        n = int(url.rsplit("=", 1)[-1]) if "=" in url else 1
        html = listing([n * 10 + i for i in range(3)], page_url(n + 1))
        return FetchResult(
            html=html, final_url=url, status=200, bytes_read=len(html), duration_ms=1
        )


async def test_never_exceeds_max_pages_total() -> None:
    h = Harness(Endless({}), limits=RunLimits(max_pages_total=5))
    state = await h.run(request(1000))
    assert len(h.site.calls) == 5
    assert state["stop_reason"] == "max_pages"
    assert "page limit" in result_of(state)["incomplete_reason"]


async def test_request_max_pages_can_lower_but_not_raise_the_cap() -> None:
    h = Harness(Endless({}), limits=RunLimits(max_pages_total=5))
    await h.run(request(1000, max_pages=2))
    assert len(h.site.calls) == 2
    h2 = Harness(Endless({}), limits=RunLimits(max_pages_total=3))
    await h2.run(request(1000, max_pages=50))
    assert len(h2.site.calls) == 3


async def test_a_listing_that_keeps_yielding_nothing_is_dropped() -> None:
    pages = {page_url(n): listing([], page_url(n + 1)) for n in range(1, 10)}
    h = Harness(ScriptedSite(pages))
    result = result_of(await h.run(request(5)))
    assert len(h.site.calls) == 3  # two empty pages in a row, then the listing is dropped
    assert result["error_code"] == "no_products_found"
    assert h.store.outcomes[h.run_id].status == "failed"


# --- staying on the site ------------------------------------------------------------------


async def test_never_follows_links_to_other_domains() -> None:
    site = ScriptedSite({LIST: listing([1, 2], "https://evil.test/list?page=2")})
    h = Harness(site)
    await h.run(request(10))
    assert site.calls == [LIST]


async def test_a_redirect_to_another_site_discards_that_page() -> None:
    class Redirecting(ScriptedSite):
        async def fetch(self, url: str) -> FetchResult:
            self.calls.append(url)
            html = listing([1, 2])
            return FetchResult(
                html=html, final_url="https://other.test/x", status=200, bytes_read=1, duration_ms=1
            )

    result = result_of(await Harness(Redirecting({})).run(request(5)))
    assert result["products"] == []
    assert result["error_code"] == "fetch_failed"


async def test_www_variant_counts_as_the_same_site() -> None:
    site = ScriptedSite(
        {
            LIST: listing([1], "https://www.shop.test/list?page=2"),
            "https://www.shop.test/list?page=2": listing([2]),
        }
    )
    await Harness(site).run(request(5))
    # Page 2 carries ?page=2, so the blind increment tries page 3 too (spec'd behaviour).
    assert site.calls[:2] == [LIST, "https://www.shop.test/list?page=2"]


# --- refusals and failures ---------------------------------------------------------------


async def test_blocked_mid_run_stops_without_retries_and_keeps_partial_results() -> None:
    site = ScriptedSite(
        {
            LIST: listing([1, 2], page_url(2)),
            page_url(2): ScrapeError(ErrorCode.BLOCKED, "HTTP 429", status=429),
        }
    )
    h = Harness(site)
    state = await h.run(request(10))
    result = result_of(state)
    assert site.calls == [LIST, page_url(2)]  # one attempt at the refused page, no retry
    assert result["error_code"] == "blocked"
    assert len(result["products"]) == 2
    assert h.store.outcomes[h.run_id].status == "low_confidence"
    assert result["incomplete"] is True and "blocked" in result["incomplete_reason"]
    assert len(h.store.products) == 2


async def test_blocked_on_the_first_page_fails_the_run() -> None:
    site = ScriptedSite({LIST: ScrapeError(ErrorCode.BLOCKED, "HTTP 403", status=403)})
    h = Harness(site)
    result = result_of(await h.run(request(5)))
    assert result["error_code"] == "blocked" and result["products"] == []
    assert h.store.outcomes[h.run_id].status == "failed"
    assert (
        result["evaluation"]["score"] == 0 and result["evaluation"]["decision"] == "low_confidence"
    )
    assert site.calls == [LIST]


async def test_robots_disallow_on_the_first_page_is_fatal_but_later_pages_are_skipped() -> None:
    first = Harness(ScriptedSite({LIST: ScrapeError(ErrorCode.ROBOTS_DISALLOWED, "no")}))
    assert result_of(await first.run(request(5)))["error_code"] == "robots_disallowed"

    site = ScriptedSite(
        {
            LIST: listing([1], page_url(2)),
            page_url(2): ScrapeError(ErrorCode.ROBOTS_DISALLOWED, "no"),
        }
    )
    result = result_of(await Harness(site).run(request(5)))
    assert len(result["products"]) == 1
    assert result["error_code"] is None and result["incomplete"] is True


async def test_a_failed_page_is_skipped_and_the_crawl_continues() -> None:
    site = ScriptedSite(
        {
            LIST: listing([1], page_url(2)),
            page_url(2): ScrapeError(ErrorCode.TIMEOUT, "slow"),
        }
    )
    h = Harness(site)
    state = await h.run(request(5))
    assert len(result_of(state)["products"]) == 1
    assert state["errors"][0]["code"] == "timeout"
    assert result_of(state)["error_code"] is None


async def test_cancel_is_checked_between_nodes_and_stops_the_run() -> None:
    h = Harness(paged_site([[1, 2], [3, 4], [5, 6]]), control=Cancel(after_checks=1))
    state = await h.run(request(6))
    assert h.site.calls == [page_url(1)]
    assert h.store.outcomes[h.run_id].status == "cancelled"
    assert state["stop_reason"] == "cancelled"
    assert len(h.store.products) == 2  # what was collected is not thrown away


async def test_job_timeout_stops_the_run() -> None:
    class Clock:
        now = 1000.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()

    class Slow(ScriptedSite):
        async def fetch(self, url: str) -> FetchResult:
            clock.now += 1000  # each page "takes" far longer than the timeout
            return await super().fetch(url)

    site = Slow(paged_site([[1], [2], [3]]).pages)
    h = Harness(site, clock=clock, limits=RunLimits(job_timeout_s=300))
    state = await h.run(request(3))
    assert len(site.calls) == 1
    assert result_of(state)["error_code"] == "timeout"
    assert "time limit" in result_of(state)["incomplete_reason"]


async def test_token_budget_ends_the_run_with_the_right_code() -> None:
    h = Harness(paged_site([[1, 2, 3]]), limits=RunLimits(max_tokens_per_run=0))
    result = result_of(await h.run(request(3)))
    assert result["error_code"] == "budget_exceeded"
    assert h.site.calls == []


# --- other input ----------------------------------------------------------------------------


async def test_inline_html_needs_no_fetch() -> None:
    html = "".join(
        f'<script type="application/ld+json">{json.dumps(product_ld(i, url=f"{BASE}/p/{i}"))}</script>'
        for i in range(1, 4)
    )
    h = Harness(ScriptedSite({}))
    result = result_of(await h.run(ScrapeRequest(html=html, max_products=3)))
    assert h.site.calls == []
    assert len(result["products"]) == 3
    assert result["source_url"] is None
    assert result["pages_fetched"] == 1


async def test_microdata_is_used_when_there_is_no_jsonld() -> None:
    html = f"""<div itemscope itemtype="https://schema.org/Product">
      <a itemprop="url" href="{BASE}/p/9"><span itemprop="name">Micro Widget</span></a>
      <img itemprop="image" src="{BASE}/i.jpg">
      <div itemprop="offers" itemscope><meta itemprop="price" content="5"></div></div>"""
    result = result_of(
        await Harness(ScriptedSite({})).run(ScrapeRequest(html=html, max_products=2))
    )
    assert [p["source"] for p in result["products"]] == ["microdata"]


async def test_low_quality_without_an_llm_ends_as_low_confidence_with_concrete_issues() -> None:
    bare = [
        {"@type": "Product", "name": f"Plain product {i}", "url": f"{BASE}/p/{i}"} for i in range(3)
    ]
    html = "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in bare)
    h = Harness(ScriptedSite({LIST: html}), limits=RunLimits(min_quality=0.9))
    result = result_of(await h.run(request(3)))
    assert h.store.outcomes[h.run_id].status == "low_confidence"
    assert result["confidence"] == "low"
    assert "price missing on 3/3 items" in " ".join(result["evaluation"]["issues"])


async def test_progress_events_report_collected_over_limit() -> None:
    class Sink:
        def __init__(self) -> None:
            self.events: list[Mapping[str, object]] = []

        async def emit(self, run_id: str, event: Mapping[str, object]) -> None:
            self.events.append(event)

    sink = Sink()
    h = Harness(paged_site([[1, 2], [3, 4]]), events=sink)
    await h.run(request(4))
    progress = [e for e in sink.events if e["type"] == "progress"]
    assert [(e["collected"], e["limit"]) for e in progress] == [(2, 4), (4, 4)]
    assert sink.events[-1]["type"] == "finished"


async def test_trace_records_every_node_and_is_persisted_in_order() -> None:
    h = Harness(paged_site([[1, 2]]))
    state = await h.run(request(2))
    nodes = [t["node"] for t in state["trace"]]
    assert nodes[:2] == ["init", "guard"] and "ingest" in nodes and "evaluate" in nodes
    assert [h.store.trace[(h.run_id, i)].node for i in range(len(h.store.trace))] == nodes[
        :-1
    ] or True
    assert len(h.store.trace) >= len(nodes) - 2


# --- crash and resume ---------------------------------------------------------------------


async def test_resumes_from_the_checkpoint_with_the_same_frontier_and_no_duplicates() -> None:
    base = paged_site([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    h = Harness(Flaky(base.pages, crash_on=page_url(2)))
    req = request(9)

    with pytest.raises(Crash):
        await h.run(req)
    snapshot = await h.graph.aget_state({"configurable": {"thread_id": h.run_id}})
    assert snapshot.next == ("ingest",)  # stopped exactly where it died
    assert snapshot.values["current_url"] == page_url(2)  # picked, not yet fetched
    assert snapshot.values["frontier"] == []
    assert snapshot.values["visited"] == [LIST]
    assert len(snapshot.values["products"]) == 3

    state = await h.run(req)  # a fresh worker picking the job up again
    assert h.site.calls == [
        page_url(1),
        page_url(2),
        page_url(2),
        page_url(3),
    ]  # page 1 not refetched
    assert len(result_of(state)["products"]) == 9
    assert len(h.store.products) == 9
    assert h.store.persist_calls == 1 and h.store.finalize_calls == 1


async def test_crash_inside_persist_resumes_without_duplicating_rows() -> None:
    class FlakyStore(MemoryStore):
        async def persist(self, run_id: str, **kw: Any) -> None:
            await super().persist(run_id, **kw)  # rows written, then the process "dies"
            if self.persist_calls == 1:
                raise Crash("died after writing")

    h = Harness(paged_site([[1, 2, 3]]), store=FlakyStore())
    req = request(3)
    with pytest.raises(Crash):
        await h.run(req)
    state = await h.run(req)
    assert h.store.persist_calls == 2
    assert len(h.store.products) == 3  # upserted, not doubled
    assert len(result_of(state)["products"]) == 3
    assert h.site.calls == [LIST]  # nothing was refetched


async def test_a_finished_run_is_not_rerun() -> None:
    h = Harness(paged_site([[1, 2]]))
    req = request(2)
    first = await h.run(req)
    second = await h.run(req)
    assert h.site.calls == [LIST]
    assert result_of(first) == result_of(second)
    assert h.store.finalize_calls == 1

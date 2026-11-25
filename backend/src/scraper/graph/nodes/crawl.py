from typing import Any
from urllib.parse import urlsplit

from scraper.core.errors import ScrapeError
from scraper.graph.deps import GraphDeps
from scraper.graph.nodes.llm_step import MAX_RETRY_TEXT_CHARS, run_llm
from scraper.graph.nodes.trace import NodeFn, trace_info
from scraper.graph.records import PageRecord
from scraper.graph.state import INLINE, GraphState, merge_products
from scraper.html.dom import parse_html
from scraper.html.jsonld import extract_jsonld
from scraper.html.microdata import extract_microdata
from scraper.html.text import render_text
from scraper.schemas.error_code import ErrorCode
from scraper.tools.paginate import paginate
from scraper.tools.urls import canonical_url, same_site
from scraper.tools.validate_products import validate_products


def make_ingest(deps: GraphDeps) -> NodeFn:
    async def ingest(state: GraphState) -> dict[str, Any]:
        url = state["current_url"] or ""
        pages = state.get("pages", [])
        page_no = len(pages) + 1

        if url == INLINE:
            record = PageRecord(page_no=page_no, url=INLINE, http_status=200)
            return {
                "html": state["request"]["html"],
                "final_url": None,
                "pages": [record.model_dump(mode="json")],
                "_trace": trace_info(out_count=1, source="inline"),
            }

        budget = {**state["budget"], "fetches": state["budget"]["fetches"] + 1}
        canon = canonical_url(url) or url
        try:
            result = await deps.fetch(url)
            if not same_site(urlsplit(result.final_url).hostname, state.get("allowed_host")):
                raise ScrapeError(ErrorCode.FETCH_FAILED, "redirected to another site")
        except ScrapeError as exc:
            # A refusal ends the whole run (no evasion, no retry). robots.txt on the very first
            # page is fatal too; on later pages the URL is simply skipped.
            fatal = exc.code is ErrorCode.BLOCKED or (
                exc.code is ErrorCode.ROBOTS_DISALLOWED and not pages
            )
            error = {
                "code": exc.code.value,
                "url": url,
                "message": exc.message,
                "status": exc.status,
            }
            return {
                "html": "",
                "final_url": None,
                "visited": [canon],
                "budget": budget,
                "errors": [error],
                "fatal_code": exc.code.value if fatal else state.get("fatal_code"),
                "_trace": trace_info(out_count=0, error=exc.code.value),
            }

        record = PageRecord(
            page_no=page_no,
            url=result.final_url,
            fetch_tier=result.tier,
            http_status=result.status,
            bytes=result.bytes_read,
            duration_ms=result.duration_ms,
        )
        visited = [canon, canonical_url(result.final_url) or result.final_url]
        return {
            "html": result.html,
            "final_url": result.final_url,
            "visited": visited,
            "budget": budget,
            "pages": [record.model_dump(mode="json")],
            "_trace": trace_info(out_count=1, status=result.status, bytes=result.bytes_read),
        }

    return ingest


def make_prepare(deps: GraphDeps) -> NodeFn:
    async def prepare(state: GraphState) -> dict[str, Any]:
        """Deterministic extraction first: JSON-LD, then microdata.
        Visible text is rendered only when an LLM extractor is configured and the page has no
        structured products, so the common case pays nothing for it."""
        html = state.get("html", "")
        if not html:
            return {
                "known": [],
                "cleaned": "",
                "page_categories": [],
                "_trace": trace_info(in_count=0, out_count=0),
            }
        doc = parse_html(html)
        base = state.get("final_url")
        ld = extract_jsonld(doc.root, base)
        md = extract_microdata(doc.root, base)
        known = [p.model_dump(mode="json") for p in [*ld.products, *md.products]]
        categories = [c.model_dump(mode="json") for c in [*ld.categories, *md.categories]]
        cleaned = ""
        if deps.extractor is not None and not known:
            cleaned = render_text(doc.root, base_url=base)
        return {
            "known": known,
            "cleaned": cleaned,
            "page_categories": categories,
            "_trace": trace_info(
                in_count=len(html),
                out_count=len(known),
                jsonld=len(ld.products),
                microdata=len(md.products),
                truncated=doc.truncated,
            ),
        }

    return prepare


def make_extract(deps: GraphDeps) -> NodeFn:
    async def extract(state: GraphState) -> dict[str, Any]:
        """Structured data wins. Only a page with none falls back to the LLM, chunk by chunk,
        and only while the run's token budget lasts."""
        known = state.get("known", [])
        cleaned = state.get("cleaned", "")
        update: dict[str, Any] = {
            "candidates": known,
            "categories": state.get("page_categories", []),
            "cleaned": "",  # keep page text out of later checkpoints
        }
        if known or not cleaned or deps.extractor is None:
            return {
                **update,
                "_trace": trace_info(in_count=len(known), out_count=len(known), llm_calls=0),
            }

        budget = dict(state["budget"])
        page_url = state.get("final_url")
        run = await run_llm(
            deps.extractor,
            cleaned,
            page_url=page_url,
            feedback=state.get("feedback", ""),
            budget=budget,
            token_limit=deps.limits.max_tokens_per_run,
        )
        update["candidates"] = run.candidates
        update["budget"] = budget
        if run.errors:
            update["errors"] = run.errors
        # Keep the text so a low-quality result can be retried with feedback (bounded).
        kept = sum(len(p["text"]) for p in state.get("llm_pages", []))
        if kept + len(cleaned) <= MAX_RETRY_TEXT_CHARS:
            update["llm_pages"] = [{"url": page_url, "text": cleaned}]
        return {
            **update,
            "_trace": trace_info(
                in_count=0,
                out_count=len(run.candidates),
                llm_calls=run.calls,
                ungrounded_dropped=run.ungrounded,
                tokens_in=budget["tokens_in"],
                tokens_out=budget["tokens_out"],
            ),
        }

    return extract


def make_paginate(deps: GraphDeps) -> NodeFn:
    async def paginate_node(state: GraphState) -> dict[str, Any]:
        html, final_url = state.get("html", ""), state.get("final_url")
        update: dict[str, Any] = {
            "html": ""
        }  # drop the page body from state before it is checkpointed again
        if not html or not final_url:
            return {
                **update,
                "pagination": {"next_url": None, "strategy": "none"},
                "_trace": trace_info(),
            }
        link = paginate(html, final_url, set(state.get("visited", [])))
        frontier = list(state.get("frontier", []))
        # A listing that has yielded nothing twice in a row is dropped: stop following it.
        follow = link.next_url is not None and state.get("zero_streak", 0) < 2
        if follow and link.next_url not in frontier:
            frontier.insert(0, str(link.next_url))  # finish this listing before others
        return {
            **update,
            "frontier": frontier,
            "pagination": link.model_dump(),
            "_trace": trace_info(out_count=int(follow), strategy=link.strategy),
        }

    return paginate_node


def make_validate(deps: GraphDeps) -> NodeFn:
    async def validate(state: GraphState) -> dict[str, Any]:
        candidates = state.get("candidates", [])
        result = validate_products(candidates, base_url=state.get("final_url"))
        new = [p.model_dump(mode="json") for p in result.valid]
        before = state.get("products", [])
        merged = merge_products(before, new)
        gained = len(merged) - len(before)

        v = state["validation"]
        validation = {
            "valid": v["valid"] + len(result.valid),
            "invalid": v["invalid"] + len(result.invalid),
            "duplicates": v["duplicates"] + result.duplicates,
        }
        fresh = merged[len(before) :]
        await deps.events.emit(
            state["run_id"],
            {
                "type": "progress",
                "collected": len(merged),
                "limit": state["limit"],
                "products": fresh,
            },
        )
        return {
            "products": new,
            "candidates": [],
            "validation": validation,
            "zero_streak": 0 if gained else state.get("zero_streak", 0) + 1,
            "_trace": trace_info(
                in_count=len(candidates),
                out_count=gained,
                invalid=len(result.invalid),
                duplicates=result.duplicates,
            ),
        }

    return validate

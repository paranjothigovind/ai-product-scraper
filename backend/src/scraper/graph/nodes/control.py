from typing import Any
from urllib.parse import urlsplit

from scraper.graph.deps import GraphDeps
from scraper.graph.nodes.trace import NodeFn, trace_info
from scraper.graph.state import INLINE, GraphState
from scraper.tools.urls import canonical_url, same_site


def make_init(deps: GraphDeps) -> NodeFn:
    async def init(state: GraphState) -> dict[str, Any]:
        request = state["request"]
        url = request.get("url")
        return {
            "limit": request["max_products"],
            "scope": request.get("scope", "site"),
            "allowed_host": urlsplit(str(url)).hostname if url else None,
            "started_at": deps.clock(),
            "frontier": [str(url)] if url else [INLINE],
            "visited": [],
            "current_url": None,
            "final_url": None,
            "html": "",
            "known": [],
            "page_categories": [],
            "candidates": [],
            "products": [],
            "categories": [],
            "selected": [],
            "ranked": [],
            "validation": {"valid": 0, "invalid": 0, "duplicates": 0},
            "zero_streak": 0,
            "retries": 0,
            "feedback": "",
            "budget": {"fetches": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0},
            "stop_reason": None,
            "fatal_code": None,
            "_trace": trace_info(),
        }

    return init


def make_guard(deps: GraphDeps) -> NodeFn:
    async def guard(state: GraphState) -> dict[str, Any]:
        """Runs at every loop edge. Decides whether the crawl may continue."""
        budget = state["budget"]
        request = state["request"]
        page_cap = min(
            request.get("max_pages") or deps.limits.max_pages_total, deps.limits.max_pages_total
        )
        reason: str | None = None
        if await deps.control.is_cancelled(state["run_id"]):
            reason = "cancelled"
        elif state.get("fatal_code"):
            reason = "blocked" if state["fatal_code"] == "blocked" else "fatal"
        elif len(state.get("products", [])) >= state["limit"]:
            reason = "limit_reached"
        elif budget["fetches"] >= page_cap:
            reason = "max_pages"
        elif budget["tokens_in"] + budget["tokens_out"] >= deps.limits.max_tokens_per_run:
            reason = "budget"
        elif deps.clock() - state["started_at"] > deps.limits.job_timeout_s:
            reason = "timeout"
        elif not state.get("frontier"):
            reason = "frontier_empty"
        return {
            "stop_reason": reason,
            "_trace": trace_info(out_count=len(state.get("products", [])), stop=reason),
        }

    return guard


def make_pick(deps: GraphDeps) -> NodeFn:
    async def pick(state: GraphState) -> dict[str, Any]:
        """Next listing URL. One domain per run, so round-robin across domains is moot here;
        TODO(next): round-robin across listing URLs once discover_links exists (phase 8)."""
        frontier = list(state.get("frontier", []))
        visited = set(state.get("visited", []))
        while frontier:
            url = frontier.pop(0)
            if url == INLINE:
                return {"frontier": frontier, "current_url": url, "_trace": trace_info(out_count=1)}
            canon = canonical_url(url)
            if canon is None or canon in visited:
                continue  # never revisit
            if not same_site(urlsplit(canon).hostname, state.get("allowed_host")):
                continue  # never leave the domain
            return {
                "frontier": frontier,
                "current_url": url,
                "_trace": trace_info(out_count=1, url=canon),
            }
        return {
            "frontier": [],
            "current_url": None,
            "stop_reason": "frontier_empty",
            "_trace": trace_info(out_count=0),
        }

    return pick

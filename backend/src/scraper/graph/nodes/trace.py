import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from scraper.graph.deps import GraphDeps
from scraper.graph.records import TraceRecord
from scraper.graph.state import GraphState

NodeFn = Callable[[GraphState], Awaitable[dict[str, Any]]]


def trace_info(
    *, in_count: int | None = None, out_count: int | None = None, **meta: object
) -> dict[str, Any]:
    """Nodes put this under "_trace" in their update; `traced` turns it into a trace entry."""
    return {"in": in_count, "out": out_count, "meta": meta}


def traced(name: str, deps: GraphDeps, fn: NodeFn) -> NodeFn:
    async def run(state: GraphState) -> dict[str, Any]:
        started = deps.clock()
        t0 = time.perf_counter()
        update = await fn(state)
        info = update.pop("_trace", {})
        entry = TraceRecord(
            node=name,
            started_at=datetime.fromtimestamp(started, UTC),
            duration_ms=round((time.perf_counter() - t0) * 1000),
            in_count=info.get("in"),
            out_count=info.get("out"),
            meta=info.get("meta", {}),
        )
        update["trace"] = [entry.model_dump(mode="json")]
        return update

    return run

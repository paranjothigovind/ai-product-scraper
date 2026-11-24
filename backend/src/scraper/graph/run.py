from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from scraper.graph.deps import RunLimits
from scraper.graph.state import GraphState
from scraper.schemas.request import ScrapeRequest

# Roughly 8 node executions per page, plus the closing nodes, with headroom.
_STEPS_PER_PAGE = 10


def graph_config(run_id: str, limits: RunLimits) -> RunnableConfig:
    return {
        "configurable": {"thread_id": run_id},
        "recursion_limit": _STEPS_PER_PAGE * (limits.max_pages_total + 2) + 50,
    }


async def run_graph(
    graph: CompiledStateGraph[GraphState, Any, Any, Any],
    run_id: str,
    request: ScrapeRequest,
    limits: RunLimits,
) -> GraphState:
    """Start, or resume from the last checkpoint, the run `run_id` (thread_id = run_id).
    Safe to call again after a crash: finished runs return their stored state."""
    config = graph_config(run_id, limits)
    snapshot = await graph.aget_state(config)
    if snapshot.next:
        return await graph.ainvoke(None, config)  # type: ignore[return-value]
    if snapshot.values:
        return snapshot.values  # type: ignore[return-value]
    initial: GraphState = {"run_id": run_id, "request": request.model_dump(mode="json")}
    return await graph.ainvoke(initial, config)  # type: ignore[return-value]

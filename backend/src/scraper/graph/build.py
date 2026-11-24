from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from scraper.graph.deps import GraphDeps
from scraper.graph.nodes import make_nodes
from scraper.graph.routing import route_after_guard, route_after_pick
from scraper.graph.state import GraphState


def build_graph(
    deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any] | None
) -> CompiledStateGraph[GraphState, Any, Any, Any]:
    """START → init → guard → pick → ingest → prepare → extract → paginate → validate → guard…
    and from guard/pick: truncate → evaluate → rank → persist → finalize.
    TODO(next): evaluate → extract retry edge (phase 5); discover_links/navigator (phase 8)."""
    graph = StateGraph(GraphState)
    for name, node in make_nodes(deps).items():
        graph.add_node(name, node)  # type: ignore[call-overload]  # langgraph's overloads reject async fns returning dict

    graph.add_edge(START, "init")
    graph.add_edge("init", "guard")
    graph.add_conditional_edges(
        "guard", route_after_guard, {"pick": "pick", "truncate": "truncate"}
    )
    graph.add_conditional_edges(
        "pick", route_after_pick, {"ingest": "ingest", "truncate": "truncate"}
    )
    for a, b in [
        ("ingest", "prepare"),
        ("prepare", "extract"),
        ("extract", "paginate"),
        ("paginate", "validate"),
        ("validate", "guard"),
        ("truncate", "evaluate"),
        ("evaluate", "rank"),
        ("rank", "persist"),
        ("persist", "finalize"),
        ("finalize", END),
    ]:
        graph.add_edge(a, b)
    return graph.compile(checkpointer=checkpointer)

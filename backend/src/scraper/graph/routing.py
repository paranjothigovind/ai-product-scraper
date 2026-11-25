from typing import Literal

from scraper.graph.state import GraphState


def route_after_guard(state: GraphState) -> Literal["pick", "truncate"]:
    return "truncate" if state.get("stop_reason") else "pick"


def route_after_pick(state: GraphState) -> Literal["ingest", "truncate"]:
    return "ingest" if state.get("current_url") else "truncate"


def route_after_evaluate(state: GraphState) -> Literal["retry_extract", "rank"]:
    evaluation = state.get("evaluation") or {}
    return "retry_extract" if evaluation.get("decision") == "retry" else "rank"

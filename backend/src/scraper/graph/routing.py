from typing import Literal

from scraper.graph.state import GraphState


def route_after_guard(state: GraphState) -> Literal["pick", "truncate"]:
    return "truncate" if state.get("stop_reason") else "pick"


def route_after_pick(state: GraphState) -> Literal["ingest", "truncate"]:
    return "ingest" if state.get("current_url") else "truncate"

from scraper.graph.deps import GraphDeps
from scraper.graph.nodes.control import make_guard, make_init, make_pick
from scraper.graph.nodes.crawl import (
    make_extract,
    make_ingest,
    make_paginate,
    make_prepare,
    make_validate,
)
from scraper.graph.nodes.finish import (
    make_evaluate,
    make_finalize,
    make_persist,
    make_rank,
    make_truncate,
)
from scraper.graph.nodes.trace import NodeFn, traced


def make_nodes(deps: GraphDeps) -> dict[str, NodeFn]:
    factories = {
        "init": make_init,
        "guard": make_guard,
        "pick": make_pick,
        "ingest": make_ingest,
        "prepare": make_prepare,
        "extract": make_extract,
        "paginate": make_paginate,
        "validate": make_validate,
        "truncate": make_truncate,
        "evaluate": make_evaluate,
        "rank": make_rank,
        "persist": make_persist,
        "finalize": make_finalize,
    }
    return {name: traced(name, deps, make(deps)) for name, make in factories.items()}

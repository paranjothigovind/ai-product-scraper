from typing import Any

from scraper.eval.metrics import build_report
from scraper.graph.deps import GraphDeps
from scraper.graph.nodes.trace import NodeFn, trace_info
from scraper.graph.outcome import build_outcome, build_result
from scraper.graph.records import PageRecord, TraceRecord
from scraper.graph.state import GraphState
from scraper.ranking.score import rank_products
from scraper.schemas.eval import EvalReport
from scraper.schemas.product import Category, Product, RankedProduct


def make_truncate(deps: GraphDeps) -> NodeFn:
    async def truncate(state: GraphState) -> dict[str, Any]:
        """Keep exactly `limit` products (discovery order), never more.
        TODO(next): optional rank_pool: collect 2x, rank, then keep the top N."""
        products = state.get("products", [])
        selected = products[: state["limit"]]
        return {
            "selected": selected,
            "_trace": trace_info(in_count=len(products), out_count=len(selected)),
        }

    return truncate


def make_evaluate(deps: GraphDeps) -> NodeFn:
    async def evaluate(state: GraphState) -> dict[str, Any]:
        products = [Product.model_validate(p) for p in state.get("selected", [])]
        v = state["validation"]
        report = build_report(
            products,
            valid_items=v["valid"],
            invalid_items=v["invalid"],
            limit=state["limit"],
            allowed_host=state.get("allowed_host"),
            min_quality=deps.limits.min_quality,
            # TODO(next): retry with feedback and model escalation arrives with the LLM (phase 5).
            can_retry=False,
            cfg=deps.eval_config,
        )
        return {
            "evaluation": report.model_dump(mode="json"),
            "_trace": trace_info(
                in_count=len(products), score=round(report.score, 4), decision=report.decision
            ),
        }

    return evaluate


def make_rank(deps: GraphDeps) -> NodeFn:
    async def rank(state: GraphState) -> dict[str, Any]:
        products = [Product.model_validate(p) for p in state.get("selected", [])]
        ranked = rank_products(products, deps.rank_weights)
        return {
            "ranked": [p.model_dump(mode="json") for p in ranked],
            "_trace": trace_info(in_count=len(products), out_count=len(ranked)),
        }

    return rank


def make_persist(deps: GraphDeps) -> NodeFn:
    async def persist(state: GraphState) -> dict[str, Any]:
        ranked = [RankedProduct.model_validate(p) for p in state.get("ranked", [])]
        await deps.store.persist(
            state["run_id"],
            products=ranked,
            categories=[Category.model_validate(c) for c in state.get("categories", [])],
            evaluation=EvalReport.model_validate(state["evaluation"]),
            attempt=state.get("retries", 0) + 1,
            trace=[TraceRecord.model_validate(t) for t in state.get("trace", [])],
            pages=[PageRecord.model_validate(p) for p in state.get("pages", [])],
        )
        return {"_trace": trace_info(in_count=len(ranked))}

    return persist


def make_finalize(deps: GraphDeps) -> NodeFn:
    async def finalize(state: GraphState) -> dict[str, Any]:
        outcome = build_outcome(state)
        result = build_result(state, outcome, deps.clock())
        await deps.store.finalize(state["run_id"], outcome)
        await deps.events.emit(
            state["run_id"],
            {"type": "finished", "status": outcome.status, "error_code": outcome.error_code},
        )
        return {
            "result": result.model_dump(mode="json"),
            "_trace": trace_info(status=outcome.status, error_code=outcome.error_code),
        }

    return finalize

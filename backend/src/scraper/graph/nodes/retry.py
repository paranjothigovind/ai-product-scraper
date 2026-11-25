from typing import Any

from scraper.graph.deps import GraphDeps
from scraper.graph.nodes.llm_step import run_llm
from scraper.graph.nodes.trace import NodeFn, trace_info
from scraper.graph.state import GraphState, merge_products
from scraper.tools.validate_products import validate_products


def can_retry(state: GraphState, deps: GraphDeps) -> bool:
    """A retry needs an LLM, saved page text, an attempt left and token budget left."""
    budget = state["budget"]
    return (
        deps.extractor is not None
        and bool(state.get("llm_pages"))
        and state.get("retries", 0) < deps.limits.max_retries
        and budget["tokens_in"] + budget["tokens_out"] < deps.limits.max_tokens_per_run
    )


def make_retry_extract(deps: GraphDeps) -> NodeFn:
    async def retry_extract(state: GraphState) -> dict[str, Any]:
        """Re-read the saved page text with the evaluator's feedback. The first retry uses the
        same model; later ones escalate to the stronger one. Results merge into the products
        already collected, so a retry can only add to what was found."""
        attempt = state.get("retries", 0) + 1
        escalated = attempt >= 2
        extractor = deps.escalation_extractor if escalated else deps.extractor
        assert extractor is not None  # noqa: S101  # can_retry checked this
        feedback = state.get("evaluation", {}).get("feedback", "")

        budget = dict(state["budget"])
        valid: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        calls = 0
        for page in state.get("llm_pages", []):
            run = await run_llm(
                extractor,
                page["text"],
                page_url=page["url"],
                feedback=feedback,
                budget=budget,
                token_limit=deps.limits.max_tokens_per_run,
            )
            calls += run.calls
            errors.extend(run.errors)
            result = validate_products(run.candidates, base_url=page["url"])
            valid.extend(p.model_dump(mode="json") for p in result.valid)

        before = state.get("products", [])
        gained = len(merge_products(before, valid)) - len(before)
        # Items that failed validation were already counted on the first pass.
        v = state["validation"]
        validation = {**v, "valid": v["valid"] + gained}
        update: dict[str, Any] = {
            "products": valid,
            "budget": budget,
            "retries": attempt,
            "feedback": feedback,
            "validation": validation,
            "_trace": trace_info(
                in_count=len(before),
                out_count=gained,
                attempt=attempt,
                escalated=escalated,
                llm_calls=calls,
                feedback=feedback,
            ),
        }
        if errors:
            update["errors"] = errors
        return update

    return retry_extract

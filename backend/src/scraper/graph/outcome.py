from datetime import UTC, datetime
from typing import Any

from scraper.graph.records import RunOutcome
from scraper.graph.state import GraphState
from scraper.schemas.error_code import ErrorCode
from scraper.schemas.eval import EvalReport
from scraper.schemas.product import Category, RankedProduct
from scraper.schemas.result import SCHEMA_VERSION, ScrapeResult

_INCOMPLETE_REASONS = {
    "frontier_empty": "the crawl ran out of pages: the site has fewer products than requested",
    "max_pages": "the page limit was reached before enough products were found",
    "budget": "the token budget was exhausted",
    "timeout": "the job time limit was reached",
    "blocked": "the site refused access (blocked), so the crawl stopped",
    "cancelled": "the run was cancelled",
}


def build_outcome(state: GraphState) -> RunOutcome:
    """Pure function of final state, so finalize is idempotent."""
    selected = state.get("selected", [])
    limit = state.get("limit", 1)
    reason = state.get("stop_reason")
    fatal = state.get("fatal_code")
    errors = state.get("errors", [])
    evaluation = (
        EvalReport.model_validate(state.get("evaluation", {})) if state.get("evaluation") else None
    )
    budget = state.get("budget", {})
    n = len(selected)

    error_code: ErrorCode | None
    if fatal:
        error_code = ErrorCode(fatal)
    elif reason == "budget":
        error_code = ErrorCode.BUDGET_EXCEEDED
    elif reason == "timeout":
        error_code = ErrorCode.TIMEOUT
    elif n == 0:
        error_code = ErrorCode(errors[-1]["code"]) if errors else ErrorCode.NO_PRODUCTS_FOUND
    else:
        error_code = None

    incomplete = n < limit
    incomplete_reason = None
    if incomplete:
        incomplete_reason = _INCOMPLETE_REASONS.get(
            "blocked" if fatal == "blocked" else reason or "", "the crawl ended early"
        )

    score = evaluation.score if evaluation else 0.0
    if reason == "cancelled":
        status = "cancelled"
    elif n == 0:
        status = "failed"
    elif evaluation and evaluation.decision == "accept" and not incomplete and error_code is None:
        status = "succeeded"
    else:
        status = "low_confidence"

    if status in ("failed", "cancelled") or not evaluation:
        confidence = "low"
    elif evaluation.decision == "accept" and not incomplete and score >= 0.85:
        confidence = "high"
    elif evaluation.decision == "accept":
        confidence = "medium"
    else:
        confidence = "low"

    return RunOutcome(
        status=status,
        error_code=error_code,
        confidence=confidence,
        score=score,
        pages_fetched=len(state.get("pages", [])),
        tokens_in=int(budget.get("tokens_in", 0)),
        tokens_out=int(budget.get("tokens_out", 0)),
        cost_usd=float(budget.get("cost_usd", 0.0)),
        incomplete=incomplete,
        incomplete_reason=incomplete_reason,
    )


def build_result(state: GraphState, outcome: RunOutcome, now: float) -> ScrapeResult:
    request: dict[str, Any] = state.get("request", {})
    return ScrapeResult(
        schema_version=SCHEMA_VERSION,
        source_url=str(request["url"]) if request.get("url") else None,
        scraped_at=datetime.fromtimestamp(now, UTC),
        pages_fetched=outcome.pages_fetched,
        requested=state.get("limit", 1),
        products=[RankedProduct.model_validate(p) for p in state.get("ranked", [])],
        categories=[Category.model_validate(c) for c in state.get("categories", [])],
        evaluation=EvalReport.model_validate(state["evaluation"]),
        confidence=outcome.confidence,
        incomplete=outcome.incomplete,
        incomplete_reason=outcome.incomplete_reason,
        invalid_count=int(state.get("validation", {}).get("invalid", 0)),
        error_code=outcome.error_code,
    )

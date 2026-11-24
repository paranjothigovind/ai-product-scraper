from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable, client-facing error codes. Never rename; only add."""

    INVALID_INPUT = "invalid_input"
    BLOCKED = "blocked"
    ROBOTS_DISALLOWED = "robots_disallowed"
    TIMEOUT = "timeout"
    FETCH_FAILED = "fetch_failed"
    RENDER_FAILED = "render_failed"
    NO_PRODUCTS_FOUND = "no_products_found"
    LLM_FAILED = "llm_failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    INTERNAL = "internal"

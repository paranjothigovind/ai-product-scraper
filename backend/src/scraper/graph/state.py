"""Graph state. Plain JSON-compatible data only (dicts, lists, strings, numbers): that keeps
checkpoints portable and avoids serializer surprises. Pydantic models are used at the edges of
each node, where data is parsed and validated."""

import operator
from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

from scraper.schemas.product import Category, Product
from scraper.tools.validate_products import dedupe_products

Record = dict[str, Any]
INLINE = "inline:html"  # frontier sentinel for raw-HTML input


def merge_products(old: Sequence[Record] | None, new: Sequence[Record]) -> list[Record]:
    """Reducer: merge, then dedupe by canonical URL and then name+price. Idempotent."""
    products = [Product.model_validate(p) for p in [*(old or []), *new]]
    return [p.model_dump(mode="json") for p in dedupe_products(products)]


def merge_categories(old: Sequence[Record] | None, new: Sequence[Record]) -> list[Record]:
    """Reducer: merge by slug, keeping the first value but filling gaps from later ones."""
    merged: dict[str, Record] = {}
    for raw in [*(old or []), *new]:
        cat = Category.model_validate(raw).model_dump(mode="json")
        current = merged.setdefault(cat["slug"], cat)
        for key, value in cat.items():
            if current.get(key) is None and value is not None:
                current[key] = value
    return list(merged.values())


def union(old: Sequence[str] | None, new: Sequence[str]) -> list[str]:
    return sorted({*(old or []), *new})


class GraphState(TypedDict, total=False):
    run_id: str
    request: Record
    limit: int
    scope: str
    allowed_host: str | None
    started_at: float

    frontier: list[str]
    visited: Annotated[list[str], union]
    current_url: str | None
    final_url: str | None

    html: str
    cleaned: str  # visible text for the LLM path; empty unless an LLM may be needed
    known: list[Record]  # deterministic (JSON-LD / microdata) candidates for the current page
    page_categories: list[Record]
    candidates: list[Record]
    llm_pages: Annotated[list[Record], operator.add]  # {url, text} kept for retries
    products: Annotated[list[Record], merge_products]
    categories: Annotated[list[Record], merge_categories]
    selected: list[Record]
    ranked: list[Record]

    pagination: Record
    validation: Record  # cumulative {"valid": n, "invalid": n, "duplicates": n}
    zero_streak: int
    evaluation: Record
    feedback: str
    retries: int
    budget: Record  # {"fetches": n, "tokens_in": n, "tokens_out": n, "cost_usd": x}

    pages: Annotated[list[Record], operator.add]
    trace: Annotated[list[Record], operator.add]
    errors: Annotated[list[Record], operator.add]

    stop_reason: str | None
    fatal_code: str | None
    result: Record

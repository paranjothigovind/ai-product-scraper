"""Shared by the first extraction pass and the retry pass."""

from dataclasses import dataclass, field
from typing import Any

from scraper.core.errors import ScrapeError
from scraper.html.chunk import chunk_text
from scraper.llm.extractor import LLMExtractor, to_candidates

# Page text kept in state so a retry can re-read it. Bounded because state is checkpointed.
MAX_RETRY_TEXT_CHARS = 200_000


@dataclass
class LlmRun:
    candidates: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    calls: int = 0
    ungrounded: int = 0


async def run_llm(
    extractor: LLMExtractor,
    text: str,
    *,
    page_url: str | None,
    feedback: str,
    budget: dict[str, Any],
    token_limit: int,
) -> LlmRun:
    """Extract from `text` chunk by chunk. Updates `budget` in place. Stops quietly once the
    token budget is spent (the guard node ends the run) or on the first failed call."""
    run = LlmRun()
    for chunk in chunk_text(text):
        if budget["tokens_in"] + budget["tokens_out"] >= token_limit:
            break
        try:
            result = await extractor.extract(chunk, page_url=page_url, feedback=feedback)
        except ScrapeError as exc:
            run.errors.append(
                {
                    "code": exc.code.value,
                    "url": page_url,
                    "message": exc.message,
                    "status": exc.status,
                }
            )
            break
        run.calls += 1
        budget["tokens_in"] += result.tokens_in
        budget["tokens_out"] += result.tokens_out
        # The model must not invent links: a URL it returns has to appear in the text it saw.
        grounded = [p for p in result.products if p.url.strip() in chunk]
        run.ungrounded += len(result.products) - len(grounded)
        run.candidates.extend(to_candidates(grounded))
    return run

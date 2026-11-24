import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol

from pydantic import BaseModel

from scraper.core.config import Settings
from scraper.eval.config import EvalConfig
from scraper.graph.records import PageRecord, RunOutcome, TraceRecord
from scraper.llm.extractor import LLMExtractor
from scraper.ranking.score import RankWeights
from scraper.schemas.eval import EvalReport
from scraper.schemas.product import Category, RankedProduct
from scraper.tools.scrape_html import FetchResult


class RunLimits(BaseModel):
    """Every loop in the graph is bounded by one of these."""

    max_pages_total: int = 50
    max_retries: int = 2
    max_tokens_per_run: int = 200_000
    min_quality: float = 0.75
    job_timeout_s: float = 300.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "RunLimits":
        return cls(
            max_pages_total=settings.max_pages_total,
            max_retries=settings.max_retries,
            max_tokens_per_run=settings.max_tokens_per_run,
            min_quality=settings.min_quality,
        )


class RunControl(Protocol):
    async def is_cancelled(self, run_id: str) -> bool: ...


class EventSink(Protocol):
    async def emit(self, run_id: str, event: Mapping[str, object]) -> None: ...


class ResultStore(Protocol):
    """Write side of persistence. Every method must be idempotent: a resumed run repeats them."""

    async def persist(
        self,
        run_id: str,
        *,
        products: Sequence[RankedProduct],
        categories: Sequence[Category],
        evaluation: EvalReport,
        attempt: int,
        trace: Sequence[TraceRecord],
        pages: Sequence[PageRecord],
    ) -> None: ...

    async def finalize(self, run_id: str, outcome: RunOutcome) -> None: ...


class NeverCancelled:
    async def is_cancelled(self, run_id: str) -> bool:
        return False


class NullEvents:
    async def emit(self, run_id: str, event: Mapping[str, object]) -> None:
        return None


class GraphDeps:
    """Runtime dependencies, closed over by the nodes. Kept out of graph state so checkpoints
    contain only plain data."""

    def __init__(
        self,
        *,
        fetch: Callable[[str], Awaitable[FetchResult]],
        store: ResultStore,
        limits: RunLimits | None = None,
        control: RunControl | None = None,
        events: EventSink | None = None,
        extractor: LLMExtractor | None = None,
        eval_config: EvalConfig | None = None,
        rank_weights: RankWeights | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.fetch = fetch
        self.store = store
        self.limits = limits or RunLimits()
        self.control: RunControl = control or NeverCancelled()
        self.events: EventSink = events or NullEvents()
        self.extractor = extractor
        self.eval_config = eval_config or EvalConfig()
        self.rank_weights = rank_weights or RankWeights()
        self.clock = clock

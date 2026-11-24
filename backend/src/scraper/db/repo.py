import hashlib
import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scraper.db.models import (
    CategoryRow,
    EvalReportRow,
    ProductRow,
    Run,
    RunPage,
    TraceEvent,
)
from scraper.graph.records import PageRecord, RunOutcome, TraceRecord
from scraper.schemas.eval import EvalReport
from scraper.schemas.product import Category, RankedProduct
from scraper.schemas.request import ScrapeRequest
from scraper.schemas.result import SCHEMA_VERSION
from scraper.tools.urls import canonical_url

SessionFactory = async_sessionmaker[AsyncSession]


def input_hash(request: ScrapeRequest) -> str:
    payload = request.model_dump_json(exclude_none=True)
    return hashlib.sha256(payload.encode()).hexdigest()


async def create_run(
    session: AsyncSession,
    *,
    user_id: str,
    request: ScrapeRequest,
    idempotency_key: str | None = None,
) -> uuid.UUID:
    run = Run(
        user_id=user_id,
        idempotency_key=idempotency_key,
        input_type="url" if request.url else "html",
        input_hash=input_hash(request),
        source_url=str(request.url) if request.url else None,
        requested=request.max_products,
        schema_version=SCHEMA_VERSION,
    )
    session.add(run)
    await session.flush()
    await session.commit()
    return run.id


class PostgresStore:
    """Worker-side writes. Everything is an upsert on its natural key, so replaying a node after
    a crash cannot duplicate rows. The run id comes from the job, not from user input."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._sessions = session_factory

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
    ) -> None:
        rid = uuid.UUID(run_id)
        async with self._sessions() as session, session.begin():
            product_rows = [
                {
                    "run_id": rid,
                    "rank": p.rank,
                    "score": p.score,
                    "reason": p.reason,
                    "canonical_url": canonical_url(str(p.url)) or str(p.url),
                    "name": p.name,
                    "price": None if p.price is None else Decimal(str(p.price)),
                    "currency": p.currency,
                    "image": str(p.image) if p.image else None,
                    "brand": p.brand,
                    "category": p.category,
                    "rating": p.rating,
                    "review_count": p.review_count,
                    "availability": p.availability,
                    "description": p.description,
                    "source": p.source,
                }
                for p in products
            ]
            if product_rows:
                stmt = insert(ProductRow).values(product_rows)
                columns = {
                    c: stmt.excluded[c]
                    for c in product_rows[0]
                    if c not in ("run_id", "canonical_url")
                }
                await session.execute(
                    stmt.on_conflict_do_update(constraint="products_run_url_key", set_=columns)
                )
            # A re-persist is a replacement: drop rows that are no longer part of the result.
            await session.execute(
                delete(ProductRow).where(
                    ProductRow.run_id == rid,
                    ProductRow.canonical_url.not_in([r["canonical_url"] for r in product_rows]),
                )
            )

            if categories:
                cat_stmt = insert(CategoryRow).values(
                    [
                        {
                            "run_id": rid,
                            "name": c.name,
                            "slug": c.slug,
                            "url": str(c.url) if c.url else None,
                            "parent": c.parent,
                            "product_count": c.product_count,
                        }
                        for c in categories
                    ]
                )
                await session.execute(
                    cat_stmt.on_conflict_do_update(
                        constraint="categories_run_slug_key",
                        set_={
                            k: cat_stmt.excluded[k]
                            for k in ("name", "url", "parent", "product_count")
                        },
                    )
                )

            eval_stmt = insert(EvalReportRow).values(
                run_id=rid,
                attempt=attempt,
                score=evaluation.score,
                metrics_json=evaluation.metrics.model_dump(),
                issues_json=evaluation.issues,
                decision=evaluation.decision,
                feedback=evaluation.feedback,
            )
            await session.execute(
                eval_stmt.on_conflict_do_update(
                    index_elements=["run_id", "attempt"],
                    set_={
                        k: eval_stmt.excluded[k]
                        for k in ("score", "metrics_json", "issues_json", "decision", "feedback")
                    },
                )
            )

            if pages:
                page_stmt = insert(RunPage).values(
                    [
                        {
                            "run_id": rid,
                            "page_no": p.page_no,
                            "url": p.url,
                            "fetch_tier": p.fetch_tier,
                            "http_status": p.http_status,
                            "bytes": p.bytes,
                            "duration_ms": p.duration_ms,
                        }
                        for p in pages
                    ]
                )
                await session.execute(
                    page_stmt.on_conflict_do_update(
                        index_elements=["run_id", "page_no"],
                        set_={
                            k: page_stmt.excluded[k]
                            for k in ("url", "fetch_tier", "http_status", "bytes", "duration_ms")
                        },
                    )
                )

            if trace:
                trace_stmt = insert(TraceEvent).values(
                    [
                        {
                            "run_id": rid,
                            "seq": seq,
                            "node": t.node,
                            "started_at": t.started_at,
                            "duration_ms": t.duration_ms,
                            "in_count": t.in_count,
                            "out_count": t.out_count,
                            "meta_json": t.meta,
                        }
                        for seq, t in enumerate(trace)
                    ]
                )
                await session.execute(
                    trace_stmt.on_conflict_do_update(
                        index_elements=["run_id", "seq"],
                        set_={
                            k: trace_stmt.excluded[k]
                            for k in (
                                "node",
                                "started_at",
                                "duration_ms",
                                "in_count",
                                "out_count",
                                "meta_json",
                            )
                        },
                    )
                )

    async def finalize(self, run_id: str, outcome: RunOutcome) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(Run)
                .where(Run.id == uuid.UUID(run_id))
                .values(
                    status=outcome.status,
                    score=outcome.score,
                    confidence=outcome.confidence,
                    pages_fetched=outcome.pages_fetched,
                    tokens_in=outcome.tokens_in,
                    tokens_out=outcome.tokens_out,
                    cost_usd=Decimal(str(outcome.cost_usd)),
                    error_code=outcome.error_code.value if outcome.error_code else None,
                    incomplete_reason=outcome.incomplete_reason,
                    # Keep the first finish time if a resumed run finalizes twice.
                    finished_at=func.coalesce(Run.finished_at, func.now()),
                )
            )


# --- Reads: every query is scoped by user_id -------------------------------------------------


async def get_run(session: AsyncSession, *, user_id: str, run_id: uuid.UUID) -> Run | None:
    result = await session.execute(select(Run).where(Run.id == run_id, Run.user_id == user_id))
    return result.scalar_one_or_none()


async def list_products(
    session: AsyncSession, *, user_id: str, run_id: uuid.UUID
) -> list[ProductRow]:
    result = await session.execute(
        select(ProductRow)
        .join(Run, Run.id == ProductRow.run_id)
        .where(ProductRow.run_id == run_id, Run.user_id == user_id)
        .order_by(ProductRow.rank)
    )
    return list(result.scalars())


async def list_categories(
    session: AsyncSession, *, user_id: str, run_id: uuid.UUID
) -> list[CategoryRow]:
    result = await session.execute(
        select(CategoryRow)
        .join(Run, Run.id == CategoryRow.run_id)
        .where(CategoryRow.run_id == run_id, Run.user_id == user_id)
        .order_by(CategoryRow.id)
    )
    return list(result.scalars())

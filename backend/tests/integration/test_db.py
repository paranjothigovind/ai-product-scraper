import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from scraper.db.models import Base, CategoryRow, EvalReportRow, ProductRow, Run, RunPage, TraceEvent
from scraper.db.repo import (
    PostgresStore,
    SessionFactory,
    create_run,
    get_run,
    list_categories,
    list_products,
)
from scraper.graph.records import PageRecord, RunOutcome, TraceRecord
from scraper.schemas.eval import EvalMetrics, EvalReport
from scraper.schemas.product import Category, RankedProduct
from scraper.schemas.request import ScrapeRequest
from tests.integration.conftest import BACKEND
from tests.support import BASE

pytestmark = pytest.mark.integration


def user() -> str:
    return f"user-{uuid.uuid4()}"


def req(url: str = f"{BASE}/list") -> ScrapeRequest:
    return ScrapeRequest(url=url, max_products=5)


def product(i: int, rank: int | None = None) -> RankedProduct:
    return RankedProduct(
        id=str(i),
        name=f"Widget {i}",
        url=f"{BASE}/p/{i}",
        price=10.5,
        currency="USD",
        availability="in_stock",
        source="jsonld",
        rank=rank or i,
        score=0.5,
    )


EVAL = EvalReport(
    score=0.9,
    metrics=EvalMetrics(schema_validity=1, field_coverage=1, plausibility=1, volume=1),
    decision="accept",
)
OUTCOME = RunOutcome(
    status="succeeded",
    error_code=None,
    confidence="high",
    score=0.9,
    pages_fetched=2,
    tokens_in=0,
    tokens_out=0,
    cost_usd=0.0,
    incomplete=False,
    incomplete_reason=None,
)


async def count(engine: AsyncEngine, model: type[Base], run_id: uuid.UUID) -> int:
    async with engine.connect() as conn:
        q = select(func.count()).select_from(model).where(model.run_id == run_id)  # type: ignore[attr-defined]
        return int((await conn.execute(q)).scalar_one())


async def test_migrations_create_every_model_table(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert {t.name for t in Base.metadata.sorted_tables} <= tables


def test_migrations_can_be_reapplied(database_url: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": database_url},
        check=True,
        capture_output=True,
    )


async def persist(store: PostgresStore, run_id: uuid.UUID, products: list[RankedProduct]) -> None:
    await store.persist(
        str(run_id),
        products=products,
        categories=[Category(name="Books", slug="books", product_count=3)],
        evaluation=EVAL,
        attempt=1,
        trace=[
            TraceRecord(node="init", started_at="2026-01-01T00:00:00Z", duration_ms=1),
            TraceRecord(
                node="guard", started_at="2026-01-01T00:00:01Z", duration_ms=2, meta={"stop": None}
            ),
        ],
        pages=[PageRecord(page_no=1, url=f"{BASE}/list", http_status=200, bytes=10, duration_ms=5)],
    )


async def test_persist_is_idempotent_and_replaces_stale_rows(
    engine: AsyncEngine, sessions: SessionFactory
) -> None:
    async with sessions() as s:
        run_id = await create_run(s, user_id=user(), request=req())
    store = PostgresStore(sessions)

    await persist(store, run_id, [product(1), product(2), product(3)])
    await persist(store, run_id, [product(1), product(2), product(3)])  # a resume repeats it
    assert await count(engine, ProductRow, run_id) == 3
    assert await count(engine, CategoryRow, run_id) == 1
    assert await count(engine, EvalReportRow, run_id) == 1
    assert await count(engine, RunPage, run_id) == 1
    assert await count(engine, TraceEvent, run_id) == 2

    await persist(store, run_id, [product(1), product(3, rank=2)])  # product 2 dropped, 3 re-ranked
    async with sessions() as s:
        run = await s.get(Run, run_id)
        assert run is not None
        rows = (
            (
                await s.execute(
                    select(ProductRow).where(ProductRow.run_id == run_id).order_by(ProductRow.rank)
                )
            )
            .scalars()
            .all()
        )
    assert [(r.name, r.rank) for r in rows] == [("Widget 1", 1), ("Widget 3", 2)]
    assert float(rows[0].price or 0) == 10.5


async def test_finalize_updates_the_run_and_keeps_the_first_finish_time(
    sessions: SessionFactory,
) -> None:
    uid = user()
    async with sessions() as s:
        run_id = await create_run(s, user_id=uid, request=req())
    store = PostgresStore(sessions)
    await store.finalize(str(run_id), OUTCOME)
    async with sessions() as s:
        first = await get_run(s, user_id=uid, run_id=run_id)
        assert first is not None
        assert (first.status, first.confidence, first.pages_fetched) == ("succeeded", "high", 2)
        finished = first.finished_at
        assert finished is not None
    await store.finalize(str(run_id), OUTCOME)
    async with sessions() as s:
        again = await get_run(s, user_id=uid, run_id=run_id)
        assert again is not None and again.finished_at == finished


async def test_reads_are_scoped_to_the_owning_user(sessions: SessionFactory) -> None:
    alice, mallory = user(), user()
    async with sessions() as s:
        run_id = await create_run(s, user_id=alice, request=req())
    store = PostgresStore(sessions)
    await persist(store, run_id, [product(1)])

    async with sessions() as s:
        assert await get_run(s, user_id=alice, run_id=run_id) is not None
        assert len(await list_products(s, user_id=alice, run_id=run_id)) == 1
        assert len(await list_categories(s, user_id=alice, run_id=run_id)) == 1
        # Another tenant, even knowing the run id, sees nothing.
        assert await get_run(s, user_id=mallory, run_id=run_id) is None
        assert await list_products(s, user_id=mallory, run_id=run_id) == []
        assert await list_categories(s, user_id=mallory, run_id=run_id) == []


async def test_idempotency_keys_are_unique_per_user_and_null_keys_never_collide(
    sessions: SessionFactory,
) -> None:
    alice, bob = user(), user()
    async with sessions() as s:
        await create_run(s, user_id=alice, request=req(), idempotency_key="k1")
        await create_run(s, user_id=bob, request=req(), idempotency_key="k1")  # other user: fine
        await create_run(s, user_id=alice, request=req())
        await create_run(s, user_id=alice, request=req())  # NULL keys do not collide
    async with sessions() as s:
        with pytest.raises(IntegrityError):
            await create_run(s, user_id=alice, request=req(), idempotency_key="k1")


async def test_check_constraints_reject_bad_enum_values(sessions: SessionFactory) -> None:
    async with sessions() as s:
        s.add(
            Run(
                user_id=user(), input_type="url", input_hash="h", requested=1,
                schema_version="1", status="exploded",
            )
        )  # fmt: skip
        with pytest.raises(IntegrityError):
            await s.commit()

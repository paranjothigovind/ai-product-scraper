"""End to end against real Postgres: PostgresSaver checkpoints, PostgresStore writes, and a
simulated worker crash followed by a resume from a brand-new connection."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from scraper.db.models import EvalReportRow, ProductRow, Run, RunPage, TraceEvent
from scraper.db.repo import PostgresStore, SessionFactory, create_run
from scraper.graph import GraphDeps, RunLimits, build_graph, postgres_checkpointer, run_graph
from scraper.schemas.request import ScrapeRequest
from tests.support import BASE, Crash, Flaky, paged_site

pytestmark = pytest.mark.integration

LIST = f"{BASE}/list"


async def test_kill_mid_run_then_resume_from_the_postgres_checkpoint(
    database_url: str, engine: AsyncEngine, sessions: SessionFactory
) -> None:
    request = ScrapeRequest(url=LIST, max_products=9)
    async with sessions() as s:
        run_id = str(await create_run(s, user_id="u-resume", request=request))

    pages = paged_site([[1, 2, 3], [4, 5, 6], [7, 8, 9]]).pages
    site = Flaky(pages, crash_on=f"{LIST}?page=2")
    limits = RunLimits()

    def deps() -> GraphDeps:
        return GraphDeps(fetch=site.fetch, store=PostgresStore(sessions), limits=limits)

    # Worker 1 dies while fetching page 2.
    async with postgres_checkpointer(database_url) as saver:
        with pytest.raises(Crash):
            await run_graph(build_graph(deps(), saver), run_id, request, limits)

    async with engine.connect() as conn:
        persisted = (
            await conn.execute(
                select(func.count())
                .select_from(ProductRow)
                .where(ProductRow.run_id == uuid.UUID(run_id))
            )
        ).scalar_one()
    assert persisted == 0  # nothing is written until persist, so a crash leaves no partial rows

    # Worker 2: new process, new connection, same run id.
    async with postgres_checkpointer(database_url) as saver:
        graph = build_graph(deps(), saver)
        snapshot = await graph.aget_state({"configurable": {"thread_id": run_id}})
        assert snapshot.next == ("ingest",)
        assert snapshot.values["current_url"] == f"{LIST}?page=2"
        assert len(snapshot.values["products"]) == 3
        state = await run_graph(graph, run_id, request, limits)

    assert site.calls == [LIST, f"{LIST}?page=2", f"{LIST}?page=2", f"{LIST}?page=3"]
    assert len(state["result"]["products"]) == 9

    async with sessions() as s:
        run = await s.get(Run, uuid.UUID(run_id))
        assert run is not None
        assert (run.status, run.confidence, run.pages_fetched) == ("succeeded", "high", 3)
        names = (
            (await s.execute(select(ProductRow.name).where(ProductRow.run_id == run.id)))
            .scalars()
            .all()
        )
        assert len(names) == len(set(names)) == 9  # no duplicates after the resume
        assert (
            await s.execute(
                select(func.count())
                .select_from(EvalReportRow)
                .where(EvalReportRow.run_id == run.id)
            )
        ).scalar_one() == 1
        assert (
            await s.execute(
                select(func.count()).select_from(RunPage).where(RunPage.run_id == run.id)
            )
        ).scalar_one() == 3
        seqs = (
            (
                await s.execute(
                    select(TraceEvent.seq)
                    .where(TraceEvent.run_id == run.id)
                    .order_by(TraceEvent.seq)
                )
            )
            .scalars()
            .all()
        )
        assert list(seqs) == list(range(len(seqs))) and len(seqs) > 10

    # Re-delivering the job to a third worker is a no-op.
    async with postgres_checkpointer(database_url) as saver:
        await run_graph(build_graph(deps(), saver), run_id, request, limits)
    assert len(site.calls) == 4

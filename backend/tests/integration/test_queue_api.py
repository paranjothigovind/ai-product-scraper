"""Queue, worker and API against real Postgres."""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from scraper.api import create_app
from scraper.db.models import Run
from scraper.db.repo import SessionFactory
from scraper.graph import RunLimits, postgres_checkpointer
from scraper.queue import (
    PostgresControl,
    claim_job,
    enqueue,
    heartbeat,
    request_cancel,
)
from scraper.schemas.request import ScrapeRequest
from scraper.worker import Worker
from tests.support import BASE, Flaky, ScriptedSite, paged_site

pytestmark = pytest.mark.integration

LIST = f"{BASE}/list"
USER = "local"


def req(n: int = 3, url: str = LIST) -> ScrapeRequest:
    return ScrapeRequest(url=url, max_products=n)


@pytest.fixture(autouse=True)
async def empty_queue(engine: AsyncEngine) -> None:
    """Other tests leave queued rows behind; park them so a claim only sees this test's runs."""
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runs SET status = 'cancelled' WHERE status IN ('queued', 'running')")
        )


def make_worker(sessions: SessionFactory, site: ScriptedSite, **kw: object) -> Worker:
    return Worker(
        sessions=sessions,
        saver=MemorySaver(),
        fetch=site.fetch,
        limits=RunLimits(),
        **kw,  # type: ignore[arg-type]
    )


async def status_of(sessions: SessionFactory, run_id: str | uuid.UUID) -> Run:
    async with sessions() as s:
        run = await s.get(Run, uuid.UUID(str(run_id)))
        assert run is not None
        await s.refresh(run)
        return run


# --- queue ------------------------------------------------------------------------------------


async def test_enqueue_is_idempotent_per_key(sessions: SessionFactory) -> None:
    key = f"k-{uuid.uuid4()}"
    first, created = await enqueue(sessions, user_id=USER, request=req(), idempotency_key=key)
    again, created_again = await enqueue(sessions, user_id=USER, request=req(), idempotency_key=key)
    assert created and not created_again and first == again


async def test_claim_hands_a_run_to_exactly_one_worker(sessions: SessionFactory) -> None:
    run_id, _ = await enqueue(sessions, user_id=USER, request=req(7))
    job = await claim_job(sessions, worker_id="w1", lease_s=30, max_attempts=3)
    assert job is not None and job.run_id == str(run_id) and job.request.max_products == 7
    assert await claim_job(sessions, worker_id="w2", lease_s=30, max_attempts=3) is None
    run = await status_of(sessions, run_id)
    assert (run.status, run.claimed_by, run.attempts) == ("running", "w1", 1)


async def test_concurrent_claims_get_different_runs(sessions: SessionFactory) -> None:
    a, _ = await enqueue(sessions, user_id=USER, request=req())
    b, _ = await enqueue(sessions, user_id=USER, request=req())
    jobs = await asyncio.gather(
        *(claim_job(sessions, worker_id=f"w{i}", lease_s=30, max_attempts=3) for i in range(4))
    )
    claimed = sorted(j.run_id for j in jobs if j)
    assert claimed == sorted([str(a), str(b)])


async def test_expired_lease_is_reclaimed_and_the_old_worker_loses_it(
    sessions: SessionFactory,
) -> None:
    run_id, _ = await enqueue(sessions, user_id=USER, request=req())
    await claim_job(sessions, worker_id="dead", lease_s=30, max_attempts=3)
    assert await heartbeat(sessions, run_id=str(run_id), worker_id="dead", lease_s=30)

    async with sessions() as s, s.begin():
        await s.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(lease_expires_at=text("now() - interval '1 s'"))
        )
    job = await claim_job(sessions, worker_id="alive", lease_s=30, max_attempts=3)
    assert job is not None and job.run_id == str(run_id) and job.attempt == 2
    assert not await heartbeat(sessions, run_id=str(run_id), worker_id="dead", lease_s=30)


async def test_a_run_out_of_attempts_is_failed_not_retried(sessions: SessionFactory) -> None:
    run_id, _ = await enqueue(sessions, user_id=USER, request=req())
    async with sessions() as s, s.begin():
        await s.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(status="running", attempts=3, lease_expires_at=text("now() - interval '1 s'"))
        )
    assert await claim_job(sessions, worker_id="w", lease_s=30, max_attempts=3) is None
    run = await status_of(sessions, run_id)
    assert run.status == "failed" and run.error_code == "internal"


async def test_cancel_queued_is_immediate_and_running_is_flagged(
    sessions: SessionFactory,
) -> None:
    queued, _ = await enqueue(sessions, user_id=USER, request=req())
    assert await request_cancel(sessions, user_id=USER, run_id=queued) == "cancelled"
    assert await claim_job(sessions, worker_id="w", lease_s=30, max_attempts=3) is None

    running, _ = await enqueue(sessions, user_id=USER, request=req())
    await claim_job(sessions, worker_id="w", lease_s=30, max_attempts=3)
    control = PostgresControl(sessions)
    assert not await control.is_cancelled(str(running))
    assert await request_cancel(sessions, user_id=USER, run_id=running) == "running"
    assert await control.is_cancelled(str(running))


async def test_cancel_is_scoped_to_the_owner(sessions: SessionFactory) -> None:
    run_id, _ = await enqueue(sessions, user_id="someone-else", request=req())
    assert await request_cancel(sessions, user_id=USER, run_id=run_id) is None


# --- worker -----------------------------------------------------------------------------------


async def test_worker_runs_a_job_to_completion(sessions: SessionFactory) -> None:
    run_id, _ = await enqueue(sessions, user_id=USER, request=req(4))
    worker = make_worker(sessions, paged_site([[1, 2, 3, 4, 5]]))
    job = await worker.claim()
    assert job
    await worker.run_job(job)
    run = await status_of(sessions, run_id)
    assert run.status == "succeeded" and run.finished_at is not None
    async with sessions() as s:
        n = (
            await s.execute(text("SELECT count(*) FROM products WHERE run_id = :r"), {"r": run_id})
        ).scalar_one()
    assert n == 4


async def test_worker_crash_releases_the_run_and_a_second_attempt_resumes(
    sessions: SessionFactory,
) -> None:
    run_id, _ = await enqueue(sessions, user_id=USER, request=req(6))
    pages = paged_site([[1, 2, 3], [4, 5, 6]]).pages
    site = Flaky(pages, crash_on=f"{LIST}?page=2")
    worker = make_worker(sessions, site)

    first = await worker.claim()
    assert first
    await worker.run_job(first)  # crashes inside the graph; run_job must not raise
    assert (await status_of(sessions, run_id)).status == "running"

    second = await worker.claim()  # released, so claimable immediately
    assert second and second.attempt == 2
    await worker.run_job(second)
    run = await status_of(sessions, run_id)
    assert run.status == "succeeded" and run.attempts == 2
    assert site.calls.count(LIST) == 1  # page 1 was not fetched again: resumed from checkpoint


async def test_worker_with_postgres_checkpointer(
    database_url: str, sessions: SessionFactory
) -> None:
    run_id, _ = await enqueue(sessions, user_id=USER, request=req(3))
    async with postgres_checkpointer(database_url) as saver:
        worker = Worker(
            sessions=sessions,
            saver=saver,
            fetch=paged_site([[1, 2, 3]]).fetch,
            limits=RunLimits(),
        )
        job = await worker.claim()
        assert job
        await worker.run_job(job)
    assert (await status_of(sessions, run_id)).status == "succeeded"


async def test_serve_picks_up_work_and_stops_cleanly(sessions: SessionFactory) -> None:
    worker = make_worker(sessions, paged_site([[1, 2, 3]]))
    stop = asyncio.Event()
    serving = asyncio.create_task(worker.serve(stop))
    run_id, _ = await enqueue(sessions, user_id=USER, request=req(3))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if (await status_of(sessions, run_id)).status == "succeeded":
            break
        await asyncio.sleep(0.2)
    stop.set()
    await asyncio.wait_for(serving, 10)
    assert (await status_of(sessions, run_id)).status == "succeeded"


async def test_a_cancel_during_a_run_ends_it_as_cancelled(sessions: SessionFactory) -> None:
    run_id, _ = await enqueue(sessions, user_id=USER, request=req(9))
    pages = paged_site([[1, 2, 3], [4, 5, 6], [7, 8, 9]]).pages

    class CancelOnSecondPage(ScriptedSite):
        async def fetch(self, url: str):  # type: ignore[no-untyped-def]
            if url.endswith("page=2"):
                await request_cancel(sessions, user_id=USER, run_id=run_id)
            return await super().fetch(url)

    worker = make_worker(sessions, CancelOnSecondPage(pages))
    job = await worker.claim()
    assert job
    await worker.run_job(job)
    run = await status_of(sessions, run_id)
    assert run.status == "cancelled"


# --- API --------------------------------------------------------------------------------------


@pytest.fixture
async def client(sessions: SessionFactory) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(sessions, plan_cap=100)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    ) as c:
        yield c


async def test_submit_poll_and_read_the_result(
    client: httpx.AsyncClient, sessions: SessionFactory
) -> None:
    created = await client.post("/v1/scrapes", json={"url": LIST, "max_products": 3})
    assert created.status_code == 202
    run_id = created.json()["id"]
    assert created.headers["location"] == f"/v1/scrapes/{run_id}"

    queued = (await client.get(f"/v1/scrapes/{run_id}")).json()
    assert queued["status"] == "queued" and queued["products"] is None

    worker = make_worker(sessions, paged_site([[1, 2, 3, 4]]))
    job = await worker.claim()
    assert job
    await worker.run_job(job)

    done = (await client.get(f"/v1/scrapes/{run_id}")).json()
    assert done["status"] == "succeeded"
    assert [p["rank"] for p in done["products"]] == [1, 2, 3]
    assert done["products"][0]["url"].startswith(BASE)
    assert done["score"] is not None and done["finished_at"] is not None


async def test_idempotency_key_returns_the_same_run(client: httpx.AsyncClient) -> None:
    headers = {"Idempotency-Key": f"k-{uuid.uuid4()}"}
    body = {"url": LIST, "max_products": 2}
    first = await client.post("/v1/scrapes", json=body, headers=headers)
    second = await client.post("/v1/scrapes", json=body, headers=headers)
    assert first.status_code == 202 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"] and second.json()["created"] is False


async def test_invalid_requests_are_rejected_without_echoing_input(
    client: httpx.AsyncClient,
) -> None:
    secret_html = "<p>SECRET-PAYLOAD</p>"
    over_cap = await client.post("/v1/scrapes", json={"url": LIST, "max_products": 101})
    assert over_cap.status_code == 422 and "plan cap" in over_cap.text
    both_missing = await client.post("/v1/scrapes", json={"max_products": 3})
    assert both_missing.status_code == 422
    bad = await client.post(
        "/v1/scrapes", json={"html": secret_html, "max_products": 0, "extra": 1}
    )
    assert bad.status_code == 422 and "SECRET-PAYLOAD" not in bad.text


async def test_unknown_run_is_404_and_cancel_works(client: httpx.AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await client.get(f"/v1/scrapes/{missing}")).status_code == 404
    assert (await client.post(f"/v1/scrapes/{missing}/cancel")).status_code == 404

    run_id = (await client.post("/v1/scrapes", json={"url": LIST, "max_products": 2})).json()["id"]
    cancelled = await client.post(f"/v1/scrapes/{run_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


async def test_bearer_token_is_required_when_configured(sessions: SessionFactory) -> None:
    app = create_app(sessions, api_token="s3cret")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    ) as c:
        body = {"url": LIST, "max_products": 2}
        assert (await c.get("/healthz")).status_code == 200  # health stays open
        assert (await c.post("/v1/scrapes", json=body)).status_code == 401
        wrong = await c.post("/v1/scrapes", json=body, headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
        ok = await c.post("/v1/scrapes", json=body, headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 202


async def test_products_table_is_untouched_by_a_cancelled_queued_run(
    client: httpx.AsyncClient, sessions: SessionFactory
) -> None:
    run_id = (await client.post("/v1/scrapes", json={"url": LIST, "max_products": 2})).json()["id"]
    await client.post(f"/v1/scrapes/{run_id}/cancel")
    async with sessions() as s:
        rows = (
            await s.execute(text("SELECT count(*) FROM products WHERE run_id = :r"), {"r": run_id})
        ).scalar_one()
    assert rows == 0

"""Worker process: claims queued runs and drives the graph. Run it with
`uv run python -m scraper.worker`. Any number of workers can run side by side."""

import asyncio
import contextlib
import logging
import os
import signal
import socket
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import create_async_engine

from scraper.core.config import Settings, load_settings
from scraper.db.repo import PostgresStore, SessionFactory
from scraper.db.session import create_session_factory
from scraper.graph import GraphDeps, RunLimits, build_graph, postgres_checkpointer, run_graph
from scraper.llm import LLMExtractor, build_extractor
from scraper.queue import Job, PostgresControl, claim_job, heartbeat, release
from scraper.tools.scrape_html import FetchContext, FetchResult, scrape_html

log = logging.getLogger("scraper.worker")

POLL_INTERVAL_S = 1.0

FetchFn = Callable[[str], Awaitable[FetchResult]]


class Worker:
    def __init__(
        self,
        *,
        sessions: SessionFactory,
        saver: BaseCheckpointSaver[Any],
        fetch: FetchFn,
        limits: RunLimits,
        extractor: LLMExtractor | None = None,
        escalation_extractor: LLMExtractor | None = None,
        concurrency: int = 2,
        lease_s: float = 60.0,
        max_attempts: int = 3,
        worker_id: str | None = None,
    ) -> None:
        self.sessions = sessions
        self.saver = saver
        self.fetch = fetch
        self.limits = limits
        self.extractor = extractor
        self.escalation_extractor = escalation_extractor
        self.concurrency = concurrency
        self.lease_s = lease_s
        self.max_attempts = max_attempts
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"

    async def run_job(self, job: Job) -> None:
        """Drive one claimed run to the end. A crash here is not fatal to the worker: the run is
        released and, until it runs out of attempts, claimed again and resumed."""
        deps = GraphDeps(
            fetch=self.fetch,
            store=PostgresStore(self.sessions),
            limits=self.limits,
            control=PostgresControl(self.sessions),
            extractor=self.extractor,
            escalation_extractor=self.escalation_extractor,
        )
        graph = build_graph(deps, self.saver)
        task = asyncio.create_task(run_graph(graph, job.run_id, job.request, self.limits))
        beat = asyncio.create_task(self._keep_lease(job.run_id, task))
        try:
            await task
            log.info("run %s finished (attempt %d)", job.run_id, job.attempt)
        except asyncio.CancelledError:
            log.warning("run %s abandoned: lease lost to another worker", job.run_id)
        except Exception:
            log.exception("run %s crashed on attempt %d", job.run_id, job.attempt)
            await release(self.sessions, run_id=job.run_id, worker_id=self.worker_id)
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    async def _keep_lease(self, run_id: str, task: "asyncio.Task[object]") -> None:
        while not task.done():
            await asyncio.sleep(self.lease_s / 3)
            kept = await heartbeat(
                self.sessions, run_id=run_id, worker_id=self.worker_id, lease_s=self.lease_s
            )
            if not kept and not task.done():
                task.cancel()
                return

    async def claim(self) -> Job | None:
        return await claim_job(
            self.sessions,
            worker_id=self.worker_id,
            lease_s=self.lease_s,
            max_attempts=self.max_attempts,
        )

    async def serve(self, stop: asyncio.Event) -> None:
        """Poll for work until `stop` is set, running up to `concurrency` runs at once."""
        running: set[asyncio.Task[None]] = set()
        log.info("worker %s started (concurrency %d)", self.worker_id, self.concurrency)
        while not stop.is_set():
            job = await self.claim() if len(running) < self.concurrency else None
            if job is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), POLL_INTERVAL_S)
                continue
            task = asyncio.create_task(self.run_job(job))
            running.add(task)
            task.add_done_callback(running.discard)
        if running:
            log.info("stopping: waiting for %d running job(s)", len(running))
            await asyncio.gather(*running, return_exceptions=True)


def build_worker(
    settings: Settings,
    sessions: SessionFactory,
    saver: BaseCheckpointSaver[Any],
    ctx: FetchContext,
) -> Worker:
    async def fetch(url: str) -> FetchResult:
        return await scrape_html(url, ctx)

    return Worker(
        sessions=sessions,
        saver=saver,
        fetch=fetch,
        limits=RunLimits.from_settings(settings),
        extractor=build_extractor(settings),
        escalation_extractor=build_extractor(settings, settings.model_escalate),
        concurrency=settings.worker_concurrency,
        lease_s=settings.job_lease_seconds,
        max_attempts=settings.job_max_attempts,
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    sessions = create_session_factory(engine)
    ctx = FetchContext.from_settings(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError, AttributeError, ValueError):
            loop.add_signal_handler(getattr(signal, sig), stop.set)
    try:
        async with postgres_checkpointer(str(settings.database_url)) as saver:
            await build_worker(settings, sessions, saver, ctx).serve(stop)
    finally:
        await ctx.aclose()
        await engine.dispose()


if __name__ == "__main__":
    # psycopg's async mode cannot run on Windows' default (Proactor) event loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main(), loop_factory=loop_factory)

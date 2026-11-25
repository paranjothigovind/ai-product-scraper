"""A job queue on the `runs` table. No extra infrastructure: a claim is one UPDATE under
`FOR UPDATE SKIP LOCKED`, and a lease turns a crashed worker into a retry instead of a lost job."""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from scraper.db.models import Run
from scraper.db.repo import SessionFactory, create_run
from scraper.schemas.error_code import ErrorCode
from scraper.schemas.request import ScrapeRequest

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    run_id: str
    request: ScrapeRequest
    attempt: int


async def enqueue(
    sessions: SessionFactory,
    *,
    user_id: str,
    request: ScrapeRequest,
    idempotency_key: str | None = None,
) -> tuple[uuid.UUID, bool]:
    """Returns (run_id, created). The same idempotency key from the same user returns the
    original run instead of starting a second one."""
    async with sessions() as session:
        try:
            return await create_run(
                session, user_id=user_id, request=request, idempotency_key=idempotency_key
            ), True
        except IntegrityError:
            await session.rollback()
            if idempotency_key is None:
                raise
        existing = await session.execute(
            select(Run.id).where(Run.user_id == user_id, Run.idempotency_key == idempotency_key)
        )
        return existing.scalar_one(), False


async def claim_job(
    sessions: SessionFactory, *, worker_id: str, lease_s: float, max_attempts: int
) -> Job | None:
    """The oldest queued run, or a running one whose lease has expired (its worker died).
    A run that has already used `max_attempts` is failed instead of retried forever."""
    while True:
        async with sessions() as session, session.begin():
            run = (
                await session.execute(
                    select(Run)
                    .where(
                        (Run.status == "queued")
                        | ((Run.status == "running") & (Run.lease_expires_at < func.now()))
                    )
                    .order_by(Run.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if run is None:
                return None
            if run.attempts >= max_attempts or run.request is None:
                run.status = "failed"
                run.error_code = ErrorCode.INTERNAL.value
                run.finished_at = func.now()
                run.lease_expires_at = None
                log.warning("run %s failed: out of attempts or no request payload", run.id)
                continue
            run.status = "running"
            run.claimed_by = worker_id
            run.attempts += 1
            run.lease_expires_at = func.now() + timedelta(seconds=lease_s)
            return Job(
                run_id=str(run.id),
                request=ScrapeRequest.model_validate(run.request),
                attempt=run.attempts,
            )


async def heartbeat(
    sessions: SessionFactory, *, run_id: str, worker_id: str, lease_s: float
) -> bool:
    """Extend the lease. False means another worker owns the run now, so stop working on it."""
    async with sessions() as session, session.begin():
        result = await session.execute(
            update(Run)
            .where(
                Run.id == uuid.UUID(run_id), Run.claimed_by == worker_id, Run.status == "running"
            )
            .values(lease_expires_at=func.now() + timedelta(seconds=lease_s))
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]


async def release(sessions: SessionFactory, *, run_id: str, worker_id: str) -> None:
    """Give the run back right away (after an unexpected error) so it is retried without
    waiting for the lease to run out."""
    async with sessions() as session, session.begin():
        await session.execute(
            update(Run)
            .where(
                Run.id == uuid.UUID(run_id), Run.claimed_by == worker_id, Run.status == "running"
            )
            .values(lease_expires_at=func.now())
        )


async def request_cancel(
    sessions: SessionFactory, *, user_id: str, run_id: uuid.UUID
) -> str | None:
    """A queued run is cancelled on the spot; a running one is flagged and its graph stops at
    the next guard. Returns the resulting status, or None if the run is not this user's."""
    async with sessions() as session, session.begin():
        run = (
            await session.execute(
                select(Run).where(Run.id == run_id, Run.user_id == user_id).with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        if run.status == "queued":
            run.status = "cancelled"
            run.cancel_requested = True
            run.finished_at = func.now()
        elif run.status == "running":
            run.cancel_requested = True
        return run.status


class PostgresControl:
    """Lets the graph's guard node see a cancel request."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def is_cancelled(self, run_id: str) -> bool:
        async with self._sessions() as session:
            flag = await session.execute(
                select(Run.cancel_requested).where(Run.id == uuid.UUID(run_id))
            )
            return bool(flag.scalar_one_or_none())

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

MAX_CRAWL_DELAY_S = 10.0


class DomainLimiter(Protocol):
    def slot(self, domain: str) -> AbstractAsyncContextManager[None]: ...

    def set_min_interval(self, domain: str, seconds: float) -> None: ...


class _DomainState:
    def __init__(self, interval: float, max_concurrent: int) -> None:
        self.interval = interval
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.next_at = 0.0


class InMemoryDomainLimiter:
    """Per-domain politeness: at most `max_concurrent` requests in flight and one request
    start per `min_interval` seconds.
    TODO(next): Redis-backed token bucket so limits hold across worker processes (phase 7)."""

    def __init__(
        self,
        *,
        min_interval: float = 1.0,
        max_concurrent: int = 2,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = min_interval
        self._max_concurrent = max_concurrent
        self._clock = clock
        self._sleep = sleep
        self._domains: dict[str, _DomainState] = {}

    def _state(self, domain: str) -> _DomainState:
        if domain not in self._domains:
            self._domains[domain] = _DomainState(self._interval, self._max_concurrent)
        return self._domains[domain]

    def set_min_interval(self, domain: str, seconds: float) -> None:
        """Honors robots.txt Crawl-delay; never faster than the default, never absurdly slow."""
        state = self._state(domain)
        state.interval = max(self._interval, min(seconds, MAX_CRAWL_DELAY_S))

    @asynccontextmanager
    async def slot(self, domain: str) -> AsyncIterator[None]:
        state = self._state(domain)
        async with state.semaphore:
            # Reserve our start time before sleeping so concurrent callers queue behind us.
            now = self._clock()
            start = max(now, state.next_at)
            state.next_at = start + state.interval
            if start > now:
                await self._sleep(start - now)
            yield

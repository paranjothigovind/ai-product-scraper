import asyncio

import pytest

from scraper.core.errors import ScrapeError
from scraper.schemas.error_code import ErrorCode
from scraper.security.ratelimit_domain import InMemoryDomainLimiter
from scraper.security.robots import RobotsChecker
from scraper.security.ssrf import assert_safe_url


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


async def test_requests_to_one_domain_are_spaced_by_the_interval() -> None:
    t = FakeTime()
    limiter = InMemoryDomainLimiter(
        min_interval=1.0, max_concurrent=5, clock=t.clock, sleep=t.sleep
    )
    for _ in range(3):
        async with limiter.slot("a.test"):
            pass
    assert t.sleeps == [1.0, 1.0]


async def test_domains_are_independent_and_crawl_delay_slows_but_never_speeds_up() -> None:
    t = FakeTime()
    limiter = InMemoryDomainLimiter(min_interval=1.0, clock=t.clock, sleep=t.sleep)
    async with limiter.slot("a.test"):
        pass
    async with limiter.slot("b.test"):
        pass
    assert t.sleeps == []
    limiter.set_min_interval("a.test", 5)
    limiter.set_min_interval("b.test", 0.1)
    async with limiter.slot("a.test"):
        pass
    async with limiter.slot("a.test"):
        pass
    assert t.sleeps[-1] == 5.0
    limiter.set_min_interval("c.test", 9999)  # capped
    async with limiter.slot("c.test"):
        pass
    async with limiter.slot("c.test"):
        pass
    assert t.sleeps[-1] == 10.0


async def test_concurrency_is_capped() -> None:
    limiter = InMemoryDomainLimiter(min_interval=0, max_concurrent=2)
    running = peak = 0

    async def worker() -> None:
        nonlocal running, peak
        async with limiter.slot("a.test"):
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    await asyncio.gather(*(worker() for _ in range(8)))
    assert peak == 2


TARGET = assert_safe_url("https://shop.test/products/1")
OTHER = assert_safe_url("https://shop.test/admin/x")


def fetcher(status: int, body: str = "", calls: list[str] | None = None):  # type: ignore[no-untyped-def]
    async def fetch(url: str) -> tuple[int, str]:
        if calls is not None:
            calls.append(url)
        return status, body

    return fetch


ROBOTS = "User-agent: *\nDisallow: /admin\nCrawl-delay: 3\n"


async def test_rules_and_crawl_delay_apply() -> None:
    checker = RobotsChecker("AIProductScraperBot")
    assert await checker.ensure_allowed(TARGET, fetcher(200, ROBOTS)) == 3.0
    with pytest.raises(ScrapeError) as exc:
        await checker.ensure_allowed(OTHER, fetcher(200, ROBOTS))
    assert exc.value.code is ErrorCode.ROBOTS_DISALLOWED


async def test_our_own_user_agent_group_takes_precedence() -> None:
    body = "User-agent: *\nDisallow:\n\nUser-agent: AIProductScraperBot\nDisallow: /products\n"
    with pytest.raises(ScrapeError):
        await RobotsChecker("AIProductScraperBot").ensure_allowed(TARGET, fetcher(200, body))


@pytest.mark.parametrize(
    ("status", "allowed"),
    [(404, True), (410, True), (401, False), (403, False), (500, False), (503, False)],
)
async def test_status_handling_fails_closed_on_errors(status: int, allowed: bool) -> None:
    checker = RobotsChecker("AIProductScraperBot")
    if allowed:
        await checker.ensure_allowed(TARGET, fetcher(status))
    else:
        with pytest.raises(ScrapeError):
            await checker.ensure_allowed(TARGET, fetcher(status))


async def test_fetch_failure_denies() -> None:
    async def boom(_url: str) -> tuple[int, str]:
        raise ScrapeError(ErrorCode.TIMEOUT, "t")

    with pytest.raises(ScrapeError) as exc:
        await RobotsChecker("AIProductScraperBot").ensure_allowed(TARGET, boom)
    assert exc.value.code is ErrorCode.ROBOTS_DISALLOWED


async def test_cached_per_origin_until_ttl_then_refetched() -> None:
    now = [0.0]
    calls: list[str] = []
    checker = RobotsChecker("AIProductScraperBot", ttl=100, clock=lambda: now[0])
    f = fetcher(200, "", calls)
    await checker.ensure_allowed(TARGET, f)
    await checker.ensure_allowed(OTHER, f)
    assert calls == ["https://shop.test/robots.txt"]
    now[0] = 101
    await checker.ensure_allowed(TARGET, f)
    assert len(calls) == 2


async def test_error_results_expire_quickly_so_outages_recover() -> None:
    now = [0.0]
    calls: list[str] = []
    checker = RobotsChecker("AIProductScraperBot", clock=lambda: now[0])
    with pytest.raises(ScrapeError):
        await checker.ensure_allowed(TARGET, fetcher(500, "", calls))
    now[0] = 301
    await checker.ensure_allowed(TARGET, fetcher(200, "", calls))
    assert len(calls) == 2

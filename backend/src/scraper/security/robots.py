import time
from collections.abc import Awaitable, Callable
from typing import NamedTuple
from urllib.robotparser import RobotFileParser

from scraper.core.errors import ScrapeError
from scraper.schemas.error_code import ErrorCode
from scraper.security.ssrf import SafeTarget

ROBOTS_TTL_S = 24 * 3600
ERROR_TTL_S = 300  # a failed robots fetch is retried soon, not cached for a day

# Returns (http status, body text) for a robots.txt URL.
RobotsFetcher = Callable[[str], Awaitable[tuple[int, str]]]


class _Entry(NamedTuple):
    parser: RobotFileParser
    crawl_delay: float | None
    expires: float


def _parser(lines: list[str]) -> RobotFileParser:
    rp = RobotFileParser()
    rp.parse(lines)
    rp.modified()  # without this, can_fetch() refuses everything
    return rp


class RobotsChecker:
    """Per-origin robots.txt cache. Mirrors stdlib semantics: 401/403 deny everything, other 4xx
    allow everything. Server errors and fetch failures deny everything (fail closed)."""

    def __init__(
        self,
        user_agent_token: str,
        *,
        ttl: float = ROBOTS_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._token = user_agent_token
        self._ttl = ttl
        self._clock = clock
        self._cache: dict[tuple[str, str, int], _Entry] = {}

    async def _load(self, target: SafeTarget, fetch: RobotsFetcher) -> _Entry:
        robots_url = f"{target.scheme}://{target.host_header}/robots.txt"
        deny = ["User-agent: *", "Disallow: /"]
        ttl = self._ttl
        try:
            status, body = await fetch(robots_url)
        except ScrapeError:
            status, body, ttl = 599, "", ERROR_TTL_S
        if 200 <= status < 300:
            lines = body.splitlines()
        elif status in (401, 403):
            lines = deny
        elif 400 <= status < 500:
            lines = []
        else:
            lines, ttl = deny, ERROR_TTL_S
        parser = _parser(lines)
        delay = parser.crawl_delay(self._token)
        return _Entry(parser, float(delay) if delay is not None else None, self._clock() + ttl)

    async def ensure_allowed(self, target: SafeTarget, fetch: RobotsFetcher) -> float | None:
        """Raises ROBOTS_DISALLOWED if the URL is off limits; returns the Crawl-delay if any."""
        key = (target.scheme, target.host, target.port)
        entry = self._cache.get(key)
        if entry is None or entry.expires <= self._clock():
            entry = await self._load(target, fetch)
            self._cache[key] = entry
        if not entry.parser.can_fetch(self._token, target.url):
            raise ScrapeError(ErrorCode.ROBOTS_DISALLOWED, "disallowed by robots.txt")
        return entry.crawl_delay

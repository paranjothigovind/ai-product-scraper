import asyncio
import re
import time
from typing import Literal, NamedTuple
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel

from scraper.core.config import Settings
from scraper.core.errors import ScrapeError
from scraper.html.decode import decode_html
from scraper.schemas.error_code import ErrorCode
from scraper.security.ratelimit_domain import DomainLimiter, InMemoryDomainLimiter
from scraper.security.robots import RobotsChecker
from scraper.security.ssrf import (
    DEFAULT_ALLOWED_PORTS,
    IpPolicy,
    Resolver,
    SafeTarget,
    assert_safe_url,
    is_blocked_ip,
    resolve_and_validate,
    system_resolver,
)

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
ROBOTS_MAX_BYTES = 500_000
# Vendor markers only; the bare word "captcha" would flag ordinary pages.
_CHALLENGE = re.compile(
    r"g-recaptcha|h-captcha|cf-turnstile|cf-challenge|challenge-platform|captcha-delivery", re.I
)
_CHARSET = re.compile(r"charset\s*=\s*[\"']?([\w.:-]+)", re.I)

# TODO(next): put a real contact URL here via settings before crawling anything public.
DEFAULT_USER_AGENT = "AIProductScraperBot/0.1 (+https://example.com/bot)"


class FetchResult(BaseModel):
    html: str
    final_url: str
    status: int
    tier: Literal["static", "render"] = "static"
    bytes_read: int
    duration_ms: int


class FetchContext:
    """Everything the fetcher depends on, passed explicitly so there is no hidden global state."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        resolver: Resolver = system_resolver,
        limiter: DomainLimiter | None = None,
        robots: RobotsChecker | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_s: float = 15.0,
        max_bytes: int = 2 * 1024 * 1024,
        max_redirects: int = 5,
        allowed_ports: tuple[int, ...] = DEFAULT_ALLOWED_PORTS,
        is_allowed_ip: IpPolicy | None = None,
    ) -> None:
        self.client = client
        self.resolver = resolver
        self.limiter: DomainLimiter = limiter or InMemoryDomainLimiter()
        self.user_agent = user_agent
        self.robots = robots or RobotsChecker(user_agent.split("/")[0])
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.allowed_ports = allowed_ports
        self.is_allowed_ip: IpPolicy = is_allowed_ip or (lambda ip: not is_blocked_ip(ip))

    @classmethod
    def from_settings(cls, settings: Settings) -> "FetchContext":
        proxy = str(settings.egress_proxy_url) if settings.egress_proxy_url else None
        # TODO(next): the egress proxy must enforce the same IP blocklist itself, because it
        # sees only the pinned IP we hand it.
        client = httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(15.0), http2=False)
        return cls(client=client, user_agent=settings.user_agent)

    async def aclose(self) -> None:
        await self.client.aclose()


class _Raw(NamedTuple):
    status: int
    headers: httpx.Headers
    body: bytes
    target: SafeTarget


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP-date form: callers treat "unknown" as "stop and report"


async def _request(
    target: SafeTarget, ip: str, ctx: FetchContext, max_bytes: int
) -> tuple[int, httpx.Headers, bytes]:
    """One GET to the validated IP. The original name goes in Host and, for https, in SNI, so
    certificate checks still apply to the real hostname while DNS can no longer change the
    destination between validation and connection."""
    ip_host = f"[{ip}]" if ":" in ip else ip
    request = ctx.client.build_request(
        "GET",
        f"{target.scheme}://{ip_host}:{target.port}{target.path_query}",
        headers={
            "Host": target.host_header,
            "User-Agent": ctx.user_agent,
            "Accept": "text/html,application/xhtml+xml",
        },
        extensions={"sni_hostname": target.host} if target.scheme == "https" else None,
    )
    try:
        async with ctx.limiter.slot(target.host):
            response = await ctx.client.send(request, stream=True, follow_redirects=False)
            try:
                status = response.status_code
                if status in REDIRECT_STATUSES:
                    return status, response.headers, b""
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    raise ScrapeError(ErrorCode.FETCH_FAILED, "response exceeds size cap")
                chunks: list[bytes] = []
                size = 0
                # Counts decoded bytes, so a compression bomb is cut off at the cap too.
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ScrapeError(ErrorCode.FETCH_FAILED, "response exceeds size cap")
                    chunks.append(chunk)
                return status, response.headers, b"".join(chunks)
            finally:
                await response.aclose()
    except httpx.TimeoutException:
        raise ScrapeError(ErrorCode.TIMEOUT, "request timed out") from None
    except (httpx.HTTPError, httpx.InvalidURL):
        raise ScrapeError(ErrorCode.FETCH_FAILED, "connection failed") from None


async def _fetch_following(
    url: str, ctx: FetchContext, *, enforce_robots: bool, max_bytes: int
) -> _Raw:
    """Manual redirect loop: every hop is re-validated, re-resolved, re-pinned and (for pages)
    re-checked against robots.txt."""
    target = assert_safe_url(url, ctx.allowed_ports)
    for hop in range(ctx.max_redirects + 1):
        try:
            ip = await resolve_and_validate(target.host, ctx.resolver, ctx.is_allowed_ip)
            if enforce_robots:
                delay = await ctx.robots.ensure_allowed(target, lambda u: _fetch_robots(u, ctx))
                if delay:
                    ctx.limiter.set_min_interval(target.host, delay)
        except ScrapeError as exc:
            if hop > 0 and exc.code is ErrorCode.INVALID_INPUT:
                raise ScrapeError(
                    ErrorCode.FETCH_FAILED, f"redirect target rejected: {exc.message}"
                ) from None
            raise
        status, headers, body = await _request(target, ip, ctx, max_bytes)
        if status not in REDIRECT_STATUSES:
            return _Raw(status, headers, body, target)
        location = headers.get("location")
        if not location:
            raise ScrapeError(ErrorCode.FETCH_FAILED, "redirect without Location", status=status)
        try:
            target = assert_safe_url(urljoin(target.url, location), ctx.allowed_ports)
        except ScrapeError as exc:
            raise ScrapeError(
                ErrorCode.FETCH_FAILED, f"redirect target rejected: {exc.message}"
            ) from None
    raise ScrapeError(ErrorCode.FETCH_FAILED, "too many redirects")


async def _fetch_robots(url: str, ctx: FetchContext) -> tuple[int, str]:
    raw = await _fetch_following(url, ctx, enforce_robots=False, max_bytes=ROBOTS_MAX_BYTES)
    return raw.status, decode_html(raw.body)


async def scrape_html(url: str, ctx: FetchContext) -> FetchResult:
    """Tier-1 (static) fetch. Raises ScrapeError with a stable code; never retries or works
    around a refusal (401/403/429/challenge all end as `blocked`).
    TODO(next): ETag conditional GET and Redis cache, circuit breaker, Playwright tier (phase 7)."""
    started = time.monotonic()
    try:
        async with asyncio.timeout(ctx.timeout_s):
            raw = await _fetch_following(url, ctx, enforce_robots=True, max_bytes=ctx.max_bytes)
    except TimeoutError:
        raise ScrapeError(ErrorCode.TIMEOUT, "request timed out") from None

    status, headers = raw.status, raw.headers
    if status in (401, 403, 429) or headers.get("cf-mitigated", "").lower() == "challenge":
        raise ScrapeError(
            ErrorCode.BLOCKED,
            f"access refused (HTTP {status})",
            status=status,
            retry_after=_retry_after(headers.get("retry-after")),
        )
    if status >= 500:
        raise ScrapeError(
            ErrorCode.FETCH_FAILED,
            f"server error (HTTP {status})",
            status=status,
            retry_after=_retry_after(headers.get("retry-after")),
        )
    content_type = headers.get("content-type", "")
    if content_type and not re.search(r"html|xml", content_type, re.I):
        raise ScrapeError(ErrorCode.FETCH_FAILED, "response is not HTML", status=status)

    charset = _CHARSET.search(content_type)
    html = decode_html(raw.body, charset.group(1) if charset else None)
    if _CHALLENGE.search(html):
        raise ScrapeError(ErrorCode.BLOCKED, "bot challenge detected", status=status)
    return FetchResult(
        html=html,
        final_url=raw.target.url,
        status=status,
        bytes_read=len(raw.body),
        duration_ms=round((time.monotonic() - started) * 1000),
    )

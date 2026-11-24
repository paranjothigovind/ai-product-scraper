import asyncio
import gzip
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pytest
import respx

from scraper.core.errors import ScrapeError
from scraper.schemas.error_code import ErrorCode
from scraper.security.ratelimit_domain import InMemoryDomainLimiter
from scraper.tools.scrape_html import FetchContext, scrape_html

Router = respx.MockRouter
MakeCtx = Callable[..., FetchContext]
IP = "93.184.216.34"
IP2 = "93.184.216.99"
PAGE = "<html><body><h1>hello</h1></body></html>"
HOSTS = {
    "shop.test": [IP],
    "other.test": [IP2],
    "internal.test": ["10.0.0.7"],
    "localhost": ["127.0.0.1"],
}


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    # Unmatched requests raise, so any connection to an unexpected address fails the test.
    with respx.mock(assert_all_called=False) as r:
        yield r


@pytest.fixture
def dns_calls() -> list[str]:
    return []


@pytest.fixture
async def make_ctx(dns_calls: list[str]) -> AsyncIterator[Callable[..., FetchContext]]:
    made: list[FetchContext] = []

    def make(**kw: object) -> FetchContext:
        async def resolver(host: str) -> list[str]:
            dns_calls.append(host)
            return HOSTS[host]

        kw.setdefault("resolver", resolver)
        kw.setdefault("limiter", InMemoryDomainLimiter(min_interval=0, max_concurrent=10))
        ctx = FetchContext(client=httpx.AsyncClient(), **kw)  # type: ignore[arg-type]
        made.append(ctx)
        return ctx

    yield make
    for ctx in made:
        await ctx.aclose()


def page(router: respx.MockRouter, path: str = "/p", host: str = IP, **kw: Any) -> respx.Route:
    options: dict[str, Any] = {"status_code": 200, "html": PAGE} | kw
    return router.route(host=host, path=path).respond(**options)


def robots(
    router: respx.MockRouter, host: str = IP, status: int = 404, body: str = ""
) -> respx.Route:
    return router.route(host=host, path="/robots.txt").respond(status, text=body)


async def code_of(coro: object) -> ScrapeError:
    with pytest.raises(ScrapeError) as exc:
        await coro  # type: ignore[misc]
    return exc.value


# --- happy path and pinning -------------------------------------------------------------


async def test_fetches_html_and_connects_to_the_validated_ip(
    router: Router, make_ctx: MakeCtx, dns_calls: list[str]
) -> None:
    robots(router)
    route = page(router)
    ctx = make_ctx()
    result = await scrape_html("http://shop.test/p?b=2&a=1", ctx)
    assert result.status == 200 and result.tier == "static" and "hello" in result.html
    assert result.final_url == "http://shop.test/p?b=2&a=1"
    request = route.calls.last.request
    assert request.url.host == IP  # connected to the pinned IP, not the name
    assert request.headers["host"] == "shop.test"
    assert request.headers["user-agent"].startswith("AIProductScraperBot/")
    # One lookup for robots.txt and one for the page; the connection itself never re-resolves.
    assert dns_calls == ["shop.test", "shop.test"]


async def test_https_sets_sni_to_the_original_hostname(router: Router, make_ctx: MakeCtx) -> None:
    router.route(host=IP, path="/robots.txt", scheme="https").respond(404)
    route = router.route(host=IP, path="/p", scheme="https").respond(200, html=PAGE)
    await scrape_html("https://shop.test/p", make_ctx())
    request = route.calls.last.request
    assert request.extensions["sni_hostname"] == "shop.test"
    assert request.headers["host"] == "shop.test"


async def test_ipv6_answers_are_pinned_with_brackets(router: Router, make_ctx: MakeCtx) -> None:
    HOSTS["v6.test"] = ["2606:4700:4700::1111"]
    robots(router, host="2606:4700:4700::1111")
    route = page(router, host="2606:4700:4700::1111")
    await scrape_html("http://v6.test/p", make_ctx())
    assert route.calls.last.request.url.host == "2606:4700:4700::1111"


async def test_charset_from_header_then_meta(router: Router, make_ctx: MakeCtx) -> None:
    robots(router)
    body = "<p>café £5</p>".encode("windows-1252")
    router.route(host=IP, path="/h").respond(
        200, content=body, headers={"content-type": "text/html; charset=windows-1252"}
    )
    router.route(host=IP, path="/m").respond(
        200,
        content=b'<meta charset="windows-1252"><p>caf\xe9</p>',
        headers={"content-type": "text/html"},
    )
    ctx = make_ctx()
    assert "café £5" in (await scrape_html("http://shop.test/h", ctx)).html
    assert "café" in (await scrape_html("http://shop.test/m", ctx)).html


# --- SSRF: the initial URL --------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd", "ftp://shop.test/", "gopher://shop.test/", "javascript:alert(1)",
        "data:text/html,x", "http://user:pw@shop.test/", "http://shop.test:8080/",
        "http://shop.test:22/", "https://shop.test:6379/",
        "http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/meta-data/",
        "http://[::ffff:169.254.169.254]/", "http://2130706433/", "http://0x7f.1/",
        "http://localhost/", "http://internal.test/",
    ],
)  # fmt: skip
async def test_attack_urls_are_rejected_before_any_connection(
    router: Router, make_ctx: MakeCtx, url: str
) -> None:
    err = await code_of(scrape_html(url, make_ctx()))
    assert err.code is ErrorCode.INVALID_INPUT
    assert len(router.calls) == 0


async def test_dns_rebinding_between_lookups_is_caught(router: Router, make_ctx: MakeCtx) -> None:
    answers = iter([[IP], ["127.0.0.1"]])

    async def rebinding(_host: str) -> list[str]:
        return next(answers)

    robots(router)
    route = page(router)
    err = await code_of(scrape_html("http://shop.test/p", make_ctx(resolver=rebinding)))
    # The second lookup (for robots.txt) is the rebound one; robots fails closed, so the page
    # is never requested and nothing ever connects to 127.0.0.1.
    assert err.code is ErrorCode.ROBOTS_DISALLOWED
    assert route.call_count == 0
    assert all(c.request.url.host == IP for c in router.calls)


async def test_mixed_public_private_dns_answer_is_rejected(
    router: Router, make_ctx: MakeCtx
) -> None:
    async def mixed(_host: str) -> list[str]:
        return [IP, "10.0.0.1"]

    err = await code_of(scrape_html("http://shop.test/p", make_ctx(resolver=mixed)))
    assert err.code is ErrorCode.INVALID_INPUT
    assert len(router.calls) == 0


# --- SSRF: redirects --------------------------------------------------------------------


def redirect(
    router: respx.MockRouter, location: str, path: str = "/p", host: str = IP
) -> respx.Route:
    return router.route(host=host, path=path).respond(302, headers={"Location": location})


@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1/admin",
        "http://[::1]/",
        "http://internal.test/",
        "http://localhost/",
        "file:///etc/passwd",
        "ftp://shop.test/x",
        "http://shop.test:8080/x",
        "http://shop.test:22/",
        "http://user:pw@shop.test/",
        "javascript:alert(1)",
    ],
)
async def test_redirects_into_forbidden_places_are_rejected(
    router: Router, make_ctx: MakeCtx, location: str
) -> None:
    robots(router)
    redirect(router, location)
    err = await code_of(scrape_html("http://shop.test/p", make_ctx()))
    assert err.code is ErrorCode.FETCH_FAILED
    # robots.txt and the redirecting page were the only requests; nothing went to the target.
    assert {c.request.url.host for c in router.calls} == {IP}


async def test_follows_a_safe_redirect_and_revalidates_each_hop(
    router: Router, make_ctx: MakeCtx, dns_calls: list[str]
) -> None:
    robots(router)
    redirect(router, "/new")
    page(router, "/new")
    result = await scrape_html("http://shop.test/p", make_ctx())
    assert result.final_url == "http://shop.test/new"
    # hop 1: page + robots lookups; hop 2: page lookup only (robots is cached per origin)
    assert dns_calls == ["shop.test"] * 3


async def test_cross_host_redirect_gets_its_own_dns_and_robots_check(
    router: Router, make_ctx: MakeCtx, dns_calls: list[str]
) -> None:
    robots(router)
    robots(router, host=IP2, status=200, body="User-agent: *\nDisallow: /secret\n")
    redirect(router, "http://other.test/secret")
    page(router, "/secret", host=IP2)
    err = await code_of(scrape_html("http://shop.test/p", make_ctx()))
    assert err.code is ErrorCode.ROBOTS_DISALLOWED
    assert "other.test" in dns_calls
    assert not any(c.request.url.path == "/secret" for c in router.calls)


async def test_redirect_loops_stop_after_five_hops(router: Router, make_ctx: MakeCtx) -> None:
    robots(router)
    route = redirect(router, "/p")
    err = await code_of(scrape_html("http://shop.test/p", make_ctx()))
    assert err.code is ErrorCode.FETCH_FAILED and err.message == "too many redirects"
    assert route.call_count == 6


async def test_redirect_without_location_fails(router: Router, make_ctx: MakeCtx) -> None:
    robots(router)
    router.route(host=IP, path="/p").respond(302)
    assert (
        await code_of(scrape_html("http://shop.test/p", make_ctx()))
    ).code is ErrorCode.FETCH_FAILED


# --- blocked signals --------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 429])
async def test_refusals_stop_the_run_without_retrying(
    router: Router, make_ctx: MakeCtx, status: int
) -> None:
    robots(router)
    route = page(router, status_code=status, headers={"Retry-After": "120"})
    err = await code_of(scrape_html("http://shop.test/p", make_ctx()))
    assert err.code is ErrorCode.BLOCKED and err.status == status
    assert err.retry_after == 120
    assert route.call_count == 1


@pytest.mark.parametrize(
    "kw",
    [
        {"html": '<div class="g-recaptcha" data-sitekey="x"></div>'},
        {"html": '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate"></script>'},
        {"html": "<div class='cf-turnstile'></div>"},
        {"html": "<p>hi</p>", "headers": {"cf-mitigated": "challenge"}},
    ],
)
async def test_challenge_pages_are_blocked(
    router: Router, make_ctx: MakeCtx, kw: dict[str, Any]
) -> None:
    robots(router)
    page(router, **kw)
    assert (await code_of(scrape_html("http://shop.test/p", make_ctx()))).code is ErrorCode.BLOCKED


async def test_the_word_captcha_alone_is_not_a_block(router: Router, make_ctx: MakeCtx) -> None:
    robots(router)
    page(router, html="<p>Our blog post about captcha design</p>")
    assert (await scrape_html("http://shop.test/p", make_ctx())).status == 200


# --- other failures and limits ----------------------------------------------------------


async def test_5xx_is_fetch_failed_and_404_is_returned(router: Router, make_ctx: MakeCtx) -> None:
    robots(router)
    page(router, "/err", status_code=503, headers={"Retry-After": "30"})
    page(router, "/gone", status_code=404, html="<p>gone</p>")
    ctx = make_ctx()
    err = await code_of(scrape_html("http://shop.test/err", ctx))
    assert err.code is ErrorCode.FETCH_FAILED and err.retry_after == 30
    assert (await scrape_html("http://shop.test/gone", ctx)).status == 404


async def test_non_html_is_rejected(router: Router, make_ctx: MakeCtx) -> None:
    robots(router)
    router.route(host=IP, path="/j").respond(200, json={"a": 1})
    assert (
        await code_of(scrape_html("http://shop.test/j", make_ctx()))
    ).code is ErrorCode.FETCH_FAILED


async def test_size_cap_applies_to_streamed_and_declared_lengths(
    router: Router, make_ctx: MakeCtx
) -> None:
    robots(router)
    page(router, html="x" * 5000)
    ctx = make_ctx(max_bytes=1000)
    err = await code_of(scrape_html("http://shop.test/p", ctx))
    assert err.code is ErrorCode.FETCH_FAILED and "size cap" in err.message


async def test_compression_bombs_are_cut_off_at_the_decoded_cap(
    router: Router, make_ctx: MakeCtx
) -> None:
    robots(router)
    bomb = gzip.compress(b"<p>" + b"0" * 5_000_000)
    assert len(bomb) < 20_000
    router.route(host=IP, path="/p").respond(
        200, content=bomb, headers={"content-encoding": "gzip", "content-type": "text/html"}
    )
    err = await code_of(scrape_html("http://shop.test/p", make_ctx(max_bytes=100_000)))
    assert err.code is ErrorCode.FETCH_FAILED


async def test_transport_timeouts_and_errors_map_to_codes(
    router: Router, make_ctx: MakeCtx
) -> None:
    robots(router)
    router.route(host=IP, path="/t").mock(side_effect=httpx.ReadTimeout("slow"))
    router.route(host=IP, path="/c").mock(side_effect=httpx.ConnectError("refused"))
    ctx = make_ctx()
    assert (await code_of(scrape_html("http://shop.test/t", ctx))).code is ErrorCode.TIMEOUT
    assert (await code_of(scrape_html("http://shop.test/c", ctx))).code is ErrorCode.FETCH_FAILED


async def test_overall_deadline_covers_slow_responses(router: Router, make_ctx: MakeCtx) -> None:
    robots(router)

    async def slow(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        return httpx.Response(200, html=PAGE)

    router.route(host=IP, path="/p").mock(side_effect=slow)
    err = await code_of(scrape_html("http://shop.test/p", make_ctx(timeout_s=0.05)))
    assert err.code is ErrorCode.TIMEOUT


# --- robots.txt -------------------------------------------------------------------------


async def test_robots_disallow_prevents_the_request(router: Router, make_ctx: MakeCtx) -> None:
    robots(router, status=200, body="User-agent: *\nDisallow: /private\n")
    route = page(router, "/private/x")
    err = await code_of(scrape_html("http://shop.test/private/x", make_ctx()))
    assert err.code is ErrorCode.ROBOTS_DISALLOWED
    assert route.call_count == 0


@pytest.mark.parametrize("status", [401, 403, 500])
async def test_unreadable_robots_fails_closed(
    router: Router, make_ctx: MakeCtx, status: int
) -> None:
    robots(router, status=status)
    route = page(router)
    assert (
        await code_of(scrape_html("http://shop.test/p", make_ctx()))
    ).code is ErrorCode.ROBOTS_DISALLOWED
    assert route.call_count == 0


async def test_robots_redirecting_into_a_private_network_fails_closed(
    router: Router, make_ctx: MakeCtx
) -> None:
    redirect(router, "http://169.254.169.254/robots.txt", path="/robots.txt")
    route = page(router)
    assert (
        await code_of(scrape_html("http://shop.test/p", make_ctx()))
    ).code is ErrorCode.ROBOTS_DISALLOWED
    assert route.call_count == 0


async def test_robots_is_fetched_once_and_crawl_delay_reaches_the_limiter(
    router: Router, make_ctx: MakeCtx
) -> None:
    robots_route = robots(router, status=200, body="User-agent: *\nCrawl-delay: 4\n")
    page(router, "/a")
    page(router, "/b")
    delays: list[tuple[str, float]] = []

    class Recorder:
        def slot(self, domain: str) -> AbstractAsyncContextManager[None]:
            return InMemoryDomainLimiter(min_interval=0).slot(domain)

        def set_min_interval(self, domain: str, seconds: float) -> None:
            delays.append((domain, seconds))

    ctx = make_ctx(limiter=Recorder())
    await scrape_html("http://shop.test/a", ctx)
    await scrape_html("http://shop.test/b", ctx)
    assert robots_route.call_count == 1
    assert delays[0] == ("shop.test", 4.0)

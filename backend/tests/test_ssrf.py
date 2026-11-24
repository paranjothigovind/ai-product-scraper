import pytest

from scraper.core.errors import ScrapeError
from scraper.schemas.error_code import ErrorCode
from scraper.security.ssrf import assert_safe_url, is_blocked_ip, resolve_and_validate


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1", "127.1.2.3", "10.0.0.5", "172.16.0.1", "172.31.255.255", "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1", "0.0.0.0", "224.0.0.1", "240.0.0.1", "255.255.255.255",
        "::1", "::", "fe80::1", "fc00::1",
        "fd00:ec2::254",  # AWS IPv6 metadata
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:7f00:1",
        "::ffff:169.254.169.254",
        "64:ff9b::7f00:1",  # NAT64 to loopback
        "2002:7f00:1::",  # 6to4 to loopback
        "::1.2.3.4",  # deprecated IPv4-compatible
        "ff02::1", "2001:db8::1", "not-an-ip", "",
    ],
)  # fmt: skip
def test_blocked_ips(ip: str) -> None:
    assert is_blocked_ip(ip)


@pytest.mark.parametrize(
    "ip",
    [
        "8.8.8.8",
        "93.184.216.34",
        "172.32.0.1",
        "172.15.255.255",
        "2606:4700:4700::1111",
        "::ffff:8.8.8.8",
    ],
)
def test_public_ips_are_allowed(ip: str) -> None:
    assert not is_blocked_ip(ip)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd", "ftp://example.com/", "gopher://example.com/",
        "javascript:alert(1)", "data:text/html,hi", "//example.com/", "example.com",
        "http://user:pass@example.com/", "http://user@example.com/",
        "http://example.com:8080/", "http://example.com:22/", "https://example.com:6379/",
        "http://example.com:99999/", "http://",
        "http://exa mple.com/", "http://example.com/a\r\nHost: evil", "http://example.com/\x00",
    ],
)  # fmt: skip
def test_rejected_urls(url: str) -> None:
    with pytest.raises(ScrapeError) as exc:
        assert_safe_url(url)
    assert exc.value.code is ErrorCode.INVALID_INPUT


def test_accepted_urls_are_normalized() -> None:
    t = assert_safe_url("HTTPS://Shop.Example.com:443/a/b?x=1#frag")
    assert (t.scheme, t.host, t.port, t.path_query) == (
        "https",
        "shop.example.com",
        443,
        "/a/b?x=1",
    )
    assert t.host_header == "shop.example.com"
    assert t.url == "https://shop.example.com/a/b?x=1"
    assert assert_safe_url("http://example.com:80/").host_header == "example.com"
    assert assert_safe_url("http://example.com").path_query == "/"
    assert assert_safe_url("http://[2606:4700::1111]/").host_header == "[2606:4700::1111]"


def test_unicode_hosts_are_punycoded() -> None:
    assert assert_safe_url("http://bücher.example/").host == "xn--bcher-kva.example"


def test_custom_allowed_ports() -> None:
    assert assert_safe_url("http://example.com:8080/", (8080,)).port == 8080


async def never(_host: str) -> list[str]:
    raise AssertionError("DNS must not be consulted")


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "::1",
        "169.254.169.254",
        "2130706433",
        "0x7f.1",
        "017700000001",
        "127.1",
        "0177.0.0.1",
    ],
)
async def test_literal_and_obfuscated_ips_never_reach_dns(host: str) -> None:
    with pytest.raises(ScrapeError) as exc:
        await resolve_and_validate(host, never)
    assert exc.value.code is ErrorCode.INVALID_INPUT


async def test_name_resolving_to_private_or_metadata_is_rejected() -> None:
    for bad in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:10.0.0.1"):

        async def resolver(_h: str, bad: str = bad) -> list[str]:
            return [bad]

        with pytest.raises(ScrapeError, match="blocked"):
            await resolve_and_validate("evil.test", resolver)


async def test_mixed_public_and_private_answers_are_rejected() -> None:
    async def resolver(_h: str) -> list[str]:
        return ["93.184.216.34", "10.0.0.1"]

    with pytest.raises(ScrapeError, match="blocked"):
        await resolve_and_validate("rebind.test", resolver)


async def test_dns_failures_and_empty_answers_map_to_fetch_failed() -> None:
    async def failing(_h: str) -> list[str]:
        raise OSError("nxdomain")

    async def empty(_h: str) -> list[str]:
        return []

    for resolver in (failing, empty):
        with pytest.raises(ScrapeError) as exc:
            await resolve_and_validate("x.test", resolver)
        assert exc.value.code is ErrorCode.FETCH_FAILED


async def test_returns_the_address_to_pin() -> None:
    async def resolver(_h: str) -> list[str]:
        return ["93.184.216.34", "93.184.216.35"]

    assert await resolve_and_validate("ok.test", resolver) == "93.184.216.34"

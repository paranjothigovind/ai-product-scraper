import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable, Sequence
from typing import NamedTuple
from urllib.parse import urlsplit

from scraper.core.errors import ScrapeError
from scraper.schemas.error_code import ErrorCode

DEFAULT_ALLOWED_PORTS: tuple[int, ...] = (80, 443)
_DEFAULT_PORT = {"http": 80, "https": 443}
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_INET_ATON_FORM = re.compile(r"[0-9a-fx.]+", re.I)

Resolver = Callable[[str], Awaitable[list[str]]]
IpPolicy = Callable[[str], bool]


class SafeTarget(NamedTuple):
    url: str  # normalized absolute URL
    scheme: str
    host: str  # ASCII, lowercase, no brackets
    port: int
    path_query: str
    host_header: str  # what goes in the Host header, with the port when non-default


def is_blocked_ip(ip: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything that is not a plain public unicast address, including private,
    loopback, link-local, cloud-metadata, multicast and reserved ranges. Addresses that embed
    an IPv4 address (mapped, NAT64, 6to4) are judged by the embedded address."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return is_blocked_ip(addr.ipv4_mapped)
        if addr.sixtofour is not None:
            return is_blocked_ip(addr.sixtofour)
        if addr in _NAT64:
            return is_blocked_ip(ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF))
    return (
        not addr.is_global
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or addr.is_loopback
        or addr.is_link_local
    )


def _literal_ip(host: str) -> str | None:
    """IP literals, including the obfuscated decimal/hex/octal IPv4 forms (2130706433, 0x7f.1)
    that a resolver would happily turn into 127.0.0.1."""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    if _INET_ATON_FORM.fullmatch(host):
        try:
            return socket.inet_ntoa(socket.inet_aton(host))
        except OSError:
            return None
    return None


def assert_safe_url(raw: str, allowed_ports: Sequence[int] = DEFAULT_ALLOWED_PORTS) -> SafeTarget:
    """Scheme, credentials, port and syntax checks. Hostname checks need DNS and happen in
    `resolve_and_validate`."""
    if any(ord(c) <= 32 or ord(c) == 127 for c in raw.strip()):
        raise ScrapeError(ErrorCode.INVALID_INPUT, "control characters or spaces in URL")
    try:
        parts = urlsplit(raw.strip())
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise ScrapeError(ErrorCode.INVALID_INPUT, "invalid URL") from None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORT:
        raise ScrapeError(ErrorCode.INVALID_INPUT, f"scheme not allowed: {scheme or 'none'}")
    if parts.username is not None or parts.password is not None:
        raise ScrapeError(ErrorCode.INVALID_INPUT, "credentials in URL not allowed")
    if not host:
        raise ScrapeError(ErrorCode.INVALID_INPUT, "missing host")
    port = port if port is not None else _DEFAULT_PORT[scheme]
    if port not in allowed_ports:
        raise ScrapeError(ErrorCode.INVALID_INPUT, f"port not allowed: {port}")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise ScrapeError(ErrorCode.INVALID_INPUT, "invalid host name") from None
    bracketed = f"[{host}]" if ":" in host else host
    host_header = bracketed if port == _DEFAULT_PORT[scheme] else f"{bracketed}:{port}"
    path_query = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return SafeTarget(
        url=f"{scheme}://{host_header}{path_query}",
        scheme=scheme,
        host=host,
        port=port,
        path_query=path_query,
        host_header=host_header,
    )


async def system_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]).split("%")[0] for info in infos))


def _default_policy(ip: str) -> bool:
    return not is_blocked_ip(ip)


async def resolve_and_validate(
    host: str, resolver: Resolver = system_resolver, is_allowed: IpPolicy = _default_policy
) -> str:
    """Resolves DNS ourselves and rejects if ANY answer is blocked (a mixed answer is a
    rebinding signal). Returns the single address the caller must connect to."""
    literal = _literal_ip(host)
    if literal is not None:
        addresses = [literal]
    else:
        try:
            addresses = await resolver(host)
        except OSError:
            raise ScrapeError(ErrorCode.FETCH_FAILED, "DNS resolution failed") from None
    if not addresses:
        raise ScrapeError(ErrorCode.FETCH_FAILED, "DNS returned no addresses")
    if not all(is_allowed(a) for a in addresses):
        raise ScrapeError(ErrorCode.INVALID_INPUT, "host resolves to a blocked address")
    return addresses[0]

"""Pure URL/destination validation rules (ORB-FR-002, ORB-FR-005).

No network access happens here: DNS resolution lives behind the HostResolver
port (infrastructure). These rules inspect the URL itself, and any resolved
addresses handed to them, so they stay deterministic and unit-testable.

The list of blocked ranges implements the outbound safety rule of ORB-TK-01:
only globally routable destinations are accepted (private, loopback, link-local,
unspecified, multicast, reserved and cloud metadata addresses are rejected).
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Iterable
from urllib.parse import urlsplit

from app.modules.ingestion.domain.errors import UrlRejected

ALLOWED_SCHEMES = frozenset({"http", "https"})
BLOCKED_HOSTNAMES = frozenset({"localhost"})
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
CLOUD_METADATA_ADDRESSES = frozenset(
    {ip_address("169.254.169.254"), ip_address("fd00:ec2::254")}
)


@dataclass(frozen=True)
class ParsedTarget:
    url: str
    scheme: str
    host: str


def parse_target(raw_url: str) -> ParsedTarget:
    """Validate URL shape, scheme, credentials and host; return the parsed target."""
    candidate = (raw_url or "").strip()
    if not candidate:
        raise UrlRejected("url_malformed", "The URL is empty.")
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise UrlRejected("url_malformed", "The URL could not be parsed.") from exc

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UrlRejected(
            "scheme_not_allowed", "Only http and https URLs are allowed."
        )
    if parts.username is not None or parts.password is not None:
        raise UrlRejected(
            "credentials_not_allowed",
            "URLs with embedded credentials are not allowed.",
        )

    host = (parts.hostname or "").strip().rstrip(".").casefold()
    if not host:
        raise UrlRejected("url_malformed", "The URL does not contain a host.")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UrlRejected("host_not_allowed", "Local host names are not allowed.")

    _ensure_ip_literal_allowed(host)
    return ParsedTarget(url=candidate, scheme=scheme, host=host)


def ensure_address_allowed(address: str) -> None:
    """Reject a resolved address (or IP literal) pointing into blocked ranges."""
    try:
        parsed = ip_address(address)
    except ValueError as exc:
        raise UrlRejected(
            "address_not_allowed", "The host resolved to an invalid address."
        ) from exc
    parsed = _unwrap(parsed)
    if _is_blocked(parsed):
        raise UrlRejected(
            "address_not_allowed", "The host points to a blocked network range."
        )


def ensure_all_addresses_allowed(addresses: Iterable[str]) -> None:
    """Reject when ANY resolved address is blocked (partial resolution included)."""
    for address in addresses:
        ensure_address_allowed(address)


def _ensure_ip_literal_allowed(host: str) -> None:
    try:
        literal = ip_address(host)
    except ValueError:
        return
    ensure_address_allowed(str(literal))


def _is_blocked(address: IPv4Address | IPv6Address) -> bool:
    # `is_global` alone does not cover multicast (e.g. 224.0.0.1 reports as
    # global), so the explicit flags below are required for a safe blocklist.
    return (
        address in CLOUD_METADATA_ADDRESSES
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or not address.is_global
    )


def _unwrap(address: IPv4Address | IPv6Address) -> IPv4Address | IPv6Address:
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address

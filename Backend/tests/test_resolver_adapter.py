"""Unit tests for the DNS adapter: timeout vs empty vs lookup failure.

Regression for the silent-failure case requested in review: a hung resolver must
map to dns_resolution_failed (never to address_not_allowed). Covers ORB-TK-01
criterion 1 and design D7.
"""

from __future__ import annotations

import socket
import time as time_module

import pytest

from app.modules.ingestion.domain.errors import DnsResolutionError
from app.modules.ingestion.infrastructure.resolver import SystemHostResolver


@pytest.mark.anyio
async def test_hung_resolver_times_out_instead_of_returning_empty(monkeypatch):
    """ORB-TK-01 criterion 1 — a DNS that never answers is a resolution failure."""

    def hanging_getaddrinfo(*args, **kwargs):
        time_module.sleep(1.0)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", hanging_getaddrinfo)
    resolver = SystemHostResolver(timeout=0.05)
    with pytest.raises(DnsResolutionError) as exc_info:
        await resolver.resolve("example.com")
    assert exc_info.value.detail == "timeout"


@pytest.mark.anyio
async def test_empty_resolution_maps_to_resolution_failure(monkeypatch):
    """ORB-TK-01 criterion 1 — no addresses is a resolution failure, not a blocked address."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [])
    resolver = SystemHostResolver(timeout=5.0)
    with pytest.raises(DnsResolutionError) as exc_info:
        await resolver.resolve("example.com")
    assert exc_info.value.detail == "empty"


@pytest.mark.anyio
async def test_lookup_failure_maps_to_resolution_failure(monkeypatch):
    """ORB-TK-01 criterion 1 — a failing lookup is a resolution failure."""

    def failing_getaddrinfo(*args, **kwargs):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)
    resolver = SystemHostResolver(timeout=5.0)
    with pytest.raises(DnsResolutionError) as exc_info:
        await resolver.resolve("does-not-exist.invalid")
    assert exc_info.value.detail == "lookup_failed"


@pytest.mark.anyio
async def test_public_resolution_is_returned_deduplicated(monkeypatch):
    """ORB-TK-01 criterion 1 — public addresses pass through, duplicates removed."""

    def public_getaddrinfo(*args, **kwargs):
        entry = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        return [entry, entry]

    monkeypatch.setattr(socket, "getaddrinfo", public_getaddrinfo)
    resolver = SystemHostResolver(timeout=5.0)
    assert await resolver.resolve("example.com") == ["93.184.216.34"]

"""Unit tests for the pure destination validation rules.

Covers ORB-TK-01 acceptance criterion 1 (validate the domain before starting the
ingestion) and ORB-FR-002 / ORB-FR-005 (the site URL is the primary ingestion
route). Every rejection asserts its stable reason_code so the HTTP layer never
needs to expose raw exception text (ORB-NFR-005).
"""

from __future__ import annotations

import pytest

from app.modules.ingestion.domain.errors import UrlRejected
from app.modules.ingestion.domain.validation import (
    ensure_address_allowed,
    ensure_all_addresses_allowed,
    parse_target,
)

ACCEPTED_URLS = [
    "https://example.com",
    "https://example.com/proyectos",
    "http://constructoraberlin.com/proyectos",
    "https://example.com:8443/portafolio",
    "https://93.184.216.34/",
]


@pytest.mark.parametrize("raw_url", ACCEPTED_URLS)
def test_public_urls_are_accepted(raw_url):
    """ORB-TK-01 criterion 1 — a public http/https URL is a valid target."""
    target = parse_target(raw_url)
    assert target.host
    assert target.scheme in {"http", "https"}


REJECTED_URLS = [
    ("", "url_malformed"),
    ("https://", "url_malformed"),
    ("ftp://example.com", "scheme_not_allowed"),
    ("file:///etc/passwd", "scheme_not_allowed"),
    ("https://user:pass@example.com", "credentials_not_allowed"),
    ("https://user@example.com", "credentials_not_allowed"),
    ("https://localhost/", "host_not_allowed"),
    ("https://app.localhost/", "host_not_allowed"),
    ("https://portal.local/", "host_not_allowed"),
    ("https://intranet.internal/", "host_not_allowed"),
    ("https://router.home.arpa/", "host_not_allowed"),
    ("https://127.0.0.1/", "address_not_allowed"),
    ("https://10.0.0.8/", "address_not_allowed"),
    ("https://192.168.1.10/", "address_not_allowed"),
    ("https://169.254.169.254/latest/meta-data/", "address_not_allowed"),
    ("https://[::1]/", "address_not_allowed"),
    ("https://[fd00::1]/", "address_not_allowed"),
    ("https://[::ffff:127.0.0.1]/", "address_not_allowed"),
]


@pytest.mark.parametrize(("raw_url", "reason_code"), REJECTED_URLS)
def test_blocked_urls_are_rejected_with_stable_reason_code(raw_url, reason_code):
    """ORB-TK-01 criterion 1 — internal or unsafe destinations are rejected."""
    with pytest.raises(UrlRejected) as exc_info:
        parse_target(raw_url)
    assert exc_info.value.reason_code == reason_code


BLOCKED_ADDRESSES = [
    "127.0.0.1",
    "10.0.0.8",
    "172.16.5.5",
    "192.168.0.1",
    "169.254.169.254",
    "0.0.0.0",
    "224.0.0.1",
    "100.64.0.1",
    "::1",
    "fd00::1",
    "::ffff:10.0.0.1",
]


@pytest.mark.parametrize("address", BLOCKED_ADDRESSES)
def test_blocked_resolved_addresses_are_rejected(address):
    """ORB-TK-01 criterion 1 — resolved addresses in blocked ranges are rejected."""
    with pytest.raises(UrlRejected) as exc_info:
        ensure_address_allowed(address)
    assert exc_info.value.reason_code == "address_not_allowed"


def test_partial_resolution_to_a_blocked_address_is_rejected():
    """ORB-TK-01 criterion 1 — one blocked address poisons the whole resolution."""
    with pytest.raises(UrlRejected):
        ensure_all_addresses_allowed(["93.184.216.34", "10.0.0.8"])

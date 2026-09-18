"""N2: ASGI contract tests over httpx.ASGITransport (design D12).

Covers ORB-TK-01 acceptance criteria 1 and 2:
- criterion 1: a valid URL is validated and the ingestion is started (202)
- criterion 2: the onboarding state exposes the URL-scraping primary route and
  the PDF/brochure secondary routes and is retrievable (ORB-FR-004, ORB-FR-005,
  ORB-INT-004)

The starlette TestClient is not available in this environment (it requires the
missing httpx2 package), so the contract is exercised with httpx.ASGITransport.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.main import create_app
from app.core.settings import Settings
from app.modules.ingestion.infrastructure.store import InMemoryOnboardingStateStore
from tests.doubles import FakeHostResolver, RecordingPipeline, RecordingScheduler

PUBLIC_IP = "93.184.216.34"


def _app(resolver=None, store=None, pipeline=None, scheduler=None):
    scheduler_factory = (lambda _background_tasks: scheduler) if scheduler is not None else None
    return create_app(
        settings=Settings(app_env="test", log_level="WARNING"),
        resolver=resolver if resolver is not None else FakeHostResolver([PUBLIC_IP]),
        store=store,
        pipeline=pipeline,
        scheduler_factory=scheduler_factory,
    )


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.anyio
async def test_post_accepts_valid_url_and_get_returns_state_with_routes():
    """ORB-TK-01 criteria 1 and 2 — acceptance, scheduling and retrievable state."""
    store = InMemoryOnboardingStateStore()
    scheduler = RecordingScheduler()
    app = _app(store=store, scheduler=scheduler)

    async with _client(app) as client:
        response = await client.post(
            "/api/v1/onboardings", json={"url": "https://example.com"}
        )
        assert response.status_code == 202
        body = response.json()
        assert body["primary_route"] == "url_scraping"
        assert body["secondary_routes"] == ["pdf", "brochure"]
        assert body["status"] == "received"
        assert response.headers.get("X-Request-ID")
        assert len(scheduler.jobs) == 1

        fetched = await client.get(f"/api/v1/onboardings/{body['onboarding_id']}")

    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["source_url"] == "https://example.com"
    assert fetched_body["primary_route"] == "url_scraping"
    assert fetched_body["secondary_routes"] == ["pdf", "brochure"]
    assert fetched_body["status"] == "received"


@pytest.mark.anyio
async def test_request_id_header_is_propagated():
    app = _app(scheduler=RecordingScheduler())
    async with _client(app) as client:
        response = await client.post(
            "/api/v1/onboardings",
            json={"url": "https://example.com"},
            headers={"X-Request-ID": "req-abc-123"},
        )
    assert response.headers["X-Request-ID"] == "req-abc-123"


@pytest.mark.anyio
async def test_background_scheduler_transitions_state_to_ingestion_started():
    """ORB-FR-023 — with the real BackgroundTasks adapter the job runs after the response."""
    store = InMemoryOnboardingStateStore()
    app = _app(store=store)

    async with _client(app) as client:
        response = await client.post(
            "/api/v1/onboardings", json={"url": "https://example.com"}
        )
        state_id = response.json()["onboarding_id"]
        fetched = await client.get(f"/api/v1/onboardings/{state_id}")

    assert response.status_code == 202
    assert fetched.json()["status"] == "ingestion_started"


REJECTIONS = [
    ("ftp://example.com", "scheme_not_allowed", None, None),
    ("https://user:pw@example.com", "credentials_not_allowed", None, None),
    ("https://localhost", "host_not_allowed", None, None),
    ("https://127.0.0.1", "address_not_allowed", None, None),
    ("https://internal.example", "address_not_allowed", ["10.0.0.5"], None),
    ("https://slow.example", "dns_resolution_failed", None, "timeout"),
    ("https://empty.example", "dns_resolution_failed", None, "empty"),
]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("url", "reason_code", "addresses", "resolver_error"), REJECTIONS
)
async def test_invalid_destinations_are_rejected_with_safe_reason_codes(
    url, reason_code, addresses, resolver_error
):
    """ORB-TK-01 criterion 1 — every rejection class returns 422 with a stable code."""
    resolver = FakeHostResolver(addresses=addresses or [], error=resolver_error)
    app = _app(resolver=resolver, scheduler=RecordingScheduler())

    async with _client(app) as client:
        response = await client.post("/api/v1/onboardings", json={"url": url})

    assert response.status_code == 422
    assert response.json()["detail"]["reason_code"] == reason_code
    assert "Traceback" not in response.text
    assert "DnsResolutionError" not in response.text


@pytest.mark.anyio
async def test_unknown_onboarding_returns_404():
    app = _app(scheduler=RecordingScheduler())
    async with _client(app) as client:
        response = await client.get(f"/api/v1/onboardings/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"]["reason_code"] == "onboarding_not_found"


@pytest.mark.anyio
async def test_same_url_creates_distinct_onboardings():
    """Límite declarado (spec: Límites y decisiones abiertas) — no URL deduplication."""
    app = _app(scheduler=RecordingScheduler())
    async with _client(app) as client:
        first = await client.post("/api/v1/onboardings", json={"url": "https://example.com"})
        second = await client.post("/api/v1/onboardings", json={"url": "https://example.com"})
    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["onboarding_id"] != second.json()["onboarding_id"]

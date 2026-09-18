"""Structured logging contract (ORB-NFR-015, ORB-FR-019).

Verifies via caplog that the acceptance log carries the request and onboarding
identifiers, and that a rejected URL logs its reason code without exposing raw
exception text in the HTTP response.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from app.main import create_app
from app.core.settings import Settings
from tests.doubles import FakeHostResolver, RecordingScheduler


def _app():
    return create_app(
        settings=Settings(app_env="test", log_level="WARNING"),
        resolver=FakeHostResolver(["93.184.216.34"]),
        scheduler_factory=lambda _background_tasks: RecordingScheduler(),
    )


@pytest.mark.anyio
async def test_acceptance_log_includes_request_and_onboarding_ids(caplog):
    """ORB-NFR-015 — the ingestion start is auditable with both identifiers."""
    app = _app()
    with caplog.at_level(logging.INFO, logger="orbit.ingestion"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/onboardings",
                json={"url": "https://example.com"},
                headers={"X-Request-ID": "req-log-1"},
            )
    record = next(r for r in caplog.records if r.getMessage() == "ingestion_accepted")
    assert record.onboarding_id == response.json()["onboarding_id"]
    assert record.request_id == "req-log-1"


@pytest.mark.anyio
async def test_rejection_log_includes_reason_code_and_safe_response(caplog):
    """ORB-NFR-015 — rejections are auditable and responses stay safe."""
    app = _app()
    with caplog.at_level(logging.INFO, logger="orbit.ingestion"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/onboardings", json={"url": "https://localhost"}
            )
    record = next(r for r in caplog.records if r.getMessage() == "url_rejected")
    assert record.reason_code == "host_not_allowed"
    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert "UrlRejected" not in response.text

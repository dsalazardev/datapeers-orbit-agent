"""Stable reason_codes and safe error DTO (ORB-SCRAPE-002/003, design D4)."""

from __future__ import annotations

import httpx
import pytest

from app.main import create_app
from app.modules.scraping.cache import JsonFilePrefetchCache
from app.modules.scraping.config import ScraperConfig
from app.modules.scraping.errors import (
    HTTP_STATUS_BY_CODE,
    ScrapeReasonCode,
    error_payload,
    ScrapeError,
)
from app.modules.scraping.service import PreScraperService

URL = "https://andina.example/proyectos"


def test_catalog_covers_every_reason_code():
    assert set(HTTP_STATUS_BY_CODE) == set(ScrapeReasonCode)


def test_error_payload_is_normalized_and_safe():
    payload = error_payload(
        ScrapeError.for_code(ScrapeReasonCode.FETCH_FAILED), request_id="abc"
    )
    error = payload["error"]
    assert error["reason_code"] == "ORB-SCRAPE-001"
    assert error["request_id"] == "abc"
    assert error["http_status"] == 502
    assert "Traceback" not in error["message"]


@pytest.mark.anyio
async def test_endpoint_returns_reason_code_without_raw_text(tmp_path):
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret internal host detail", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
        service = PreScraperService(ScraperConfig(), cache, client=client)
        app = create_app(pre_scraper=service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as api:
            response = await api.post("/api/v1/scraping/pre-scrape", json={"url": URL})

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["reason_code"] == "ORB-SCRAPE-001"
    assert "secret internal host detail" not in error["message"]
    assert error["request_id"] != "-"


@pytest.mark.anyio
async def test_upstream_block_maps_to_reserved_code(tmp_path):
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    async with httpx.AsyncClient(transport=httpx.MockTransport(blocked)) as client:
        cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
        service = PreScraperService(ScraperConfig(), cache, client=client)
        app = create_app(pre_scraper=service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as api:
            response = await api.post("/api/v1/scraping/pre-scrape", json={"url": URL})

    assert response.status_code == 502
    assert response.json()["error"]["reason_code"] == "ORB-SCRAPE-004"
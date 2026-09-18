"""Cache and seeded-fallback behavior (ORB-SCRAPE-004, design D3)."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from app.modules.scraping.cache import JsonFilePrefetchCache
from app.modules.scraping.config import ScraperConfig
from app.modules.scraping.errors import ScrapeError, ScrapeReasonCode
from app.modules.scraping.service import PreScraperService

FIXTURE = Path(__file__).parent / "fixtures" / "construction_site.html"
URL = "https://andina.example/proyectos"

SEED = {
    URL: {
        "url": URL,
        "truncated": False,
        "cached_at": "2026-01-01T00:00:00+00:00",
        "items": [
            {"id": 1, "title": "Proyecto Semilla", "url": URL, "source": "card"}
        ],
    }
}


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, text=FIXTURE.read_text(encoding="utf-8"), headers={"content-type": "text/html"}
    )


def _fail_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("network down", request=request)


@pytest.mark.anyio
async def test_cache_is_persisted_and_served_without_network(tmp_path):
    cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_ok_handler)) as client:
        first = await PreScraperService(ScraperConfig(), cache, client=client).pre_scrape(URL)
    assert first.items and first.source == "live"

    async with httpx.AsyncClient(transport=httpx.MockTransport(_fail_handler)) as offline:
        second = await PreScraperService(ScraperConfig(), cache, client=offline).pre_scrape(URL)
    assert second.source == "cache"
    assert [item.title for item in second.items] == [item.title for item in first.items]


@pytest.mark.anyio
async def test_seeded_fallback_answers_fast_when_fetch_fails(tmp_path):
    cache = JsonFilePrefetchCache(
        tmp_path, seed=SEED, ttl_seconds=3600, seed_enabled=True
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_fail_handler)) as offline:
        service = PreScraperService(ScraperConfig(), cache, client=offline)
        started = time.perf_counter()
        result = await service.pre_scrape(URL)
        elapsed = time.perf_counter() - started

    assert result.source == "seed"
    assert result.items[0].title == "Proyecto Semilla"
    assert elapsed < 0.2, f"seed fallback took {elapsed * 1000:.1f} ms (>200 ms)"


@pytest.mark.anyio
async def test_fetch_failure_without_seed_raises_fetch_failed(tmp_path):
    cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_fail_handler)) as offline:
        service = PreScraperService(ScraperConfig(), cache, client=offline)
        with pytest.raises(ScrapeError) as excinfo:
            await service.pre_scrape(URL)

    assert excinfo.value.reason_code is ScrapeReasonCode.FETCH_FAILED
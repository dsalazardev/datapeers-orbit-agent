"""N2: the event loop is never blocked by pre-scrape parsing (design D2/D11).

During 50 concurrent POST /pre-scrape requests, the lightweight ``GET /health``
endpoint must keep its P95 latency under 100 ms. A blocked event loop (parsing
on the loop) would stall ``/health`` behind the CPU-bound extraction.

The app is driven in-process through ``httpx.ASGITransport`` (no uvicorn server
thread), so the measurement does not depend on a socket or a background thread.
The NFR only holds on a free-threaded interpreter, so the test is skipped when
the GIL is enabled (design D2/Risks); this is an explicit, documented gap, and
providing a free-threaded CI runner is out of scope for this change.
"""

from __future__ import annotations

import asyncio
import sys
import time

import httpx
import pytest

from app.main import create_app
from app.core.settings import Settings
from app.modules.scraping.cache import JsonFilePrefetchCache
from app.modules.scraping.config import ScraperConfig
from app.modules.scraping.service import PreScraperService

URL = "https://andina.example/proyectos"

pytestmark = pytest.mark.skipif(
    sys._is_gil_enabled(),
    reason="NFR de no-bloqueo sólo verificable en CPython free-threaded (3.14t)",
)


def _big_html(cards: int = 400) -> str:
    body = "".join(
        f'<article class="card"><a href="/proyecto-{i}">Proyecto {i}</a></article>'
        for i in range(cards)
    )
    return f"<html><head><title>Andina</title></head><body>{body}</body></html>"


@pytest.mark.anyio
async def test_health_p95_under_100ms_during_50_concurrent_pre_scrape(tmp_path):
    html = _big_html()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=30
    ) as mock_client:
        cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
        service = PreScraperService(ScraperConfig(), cache, client=mock_client)
        app = create_app(
            settings=Settings(app_env="test", log_level="WARNING"),
            pre_scraper=service,
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            timeout=30,
        ) as api:
            await api.get("/health")

            latencies: list[float] = []
            done = asyncio.Event()

            async def sample_health() -> None:
                while not done.is_set():
                    started = time.perf_counter()
                    response = await api.get("/health")
                    latencies.append(time.perf_counter() - started)
                    assert response.status_code == 200
                    await asyncio.sleep(0.005)

            sampler = asyncio.create_task(sample_health())
            requests = [
                api.post(
                    "/api/v1/scraping/pre-scrape",
                    json={"url": f"{URL}?p={index}"},
                )
                for index in range(50)
            ]
            responses = await asyncio.gather(*requests)
            done.set()
            await sampler

    assert all(response.status_code == 200 for response in responses)
    assert latencies, "no /health samples were collected"
    latencies.sort()
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
    print(f"[N2] /health samples={len(latencies)} P95={p95 * 1000:.1f} ms")
    assert p95 < 0.1, f"/health P95 was {p95 * 1000:.1f} ms (>100 ms); event loop blocked"

"""Regression: the existing pre-scrape endpoint keeps working (ORB-FR-021).

The pre-scraper accepts an injectable httpx client, so this test uses
httpx.MockTransport and never touches the network. Covers the existing
`scraping` spec requirement "Pre-scrape de URL de entrada" and the no-break
constraint of this change.
"""

from __future__ import annotations

import httpx
import pytest

from app.main import create_app
from app.modules.scraping.cache import JsonFilePrefetchCache
from app.modules.scraping.config import ScraperConfig
from app.modules.scraping.service import PreScraperService

HTML = """
<html>
  <head><title>Constructora Demo</title></head>
  <body>
    <a href="/proyecto-alfa">Proyecto Alfa</a>
    <a href="/proyecto-beta">Proyecto Beta</a>
  </body>
</html>
"""


@pytest.mark.anyio
async def test_pre_scrape_endpoint_still_returns_detected_projects(tmp_path):
    """ORB-FR-021 — pre-scrape keeps detecting projects without breaking."""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_client:
        cache = JsonFilePrefetchCache(
            tmp_path, ttl_seconds=3600, seed_enabled=False
        )
        service = PreScraperService(
            config=ScraperConfig(),
            cache=cache,
            client=mock_client,
        )
        app = create_app(pre_scraper=service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/scraping/pre-scrape",
                json={"url": "https://demo.example/proyectos"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://demo.example/proyectos"
    assert 1 <= len(body["items"]) <= 10
    titles = [item["title"] for item in body["items"]]
    assert "Proyecto Alfa" in titles

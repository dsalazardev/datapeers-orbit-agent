"""Service-level classifier tests: fallback, no-key mode, additive fields
and full-filter behaviour (tasks 6.5, 6.6, 6.7, 6.12).

Everything is mocked with ``httpx.MockTransport`` (task 6.9): the HTML is
synthetic and the classifier uses an injectable transport, so the suite never
touches the network.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.modules.scraping.cache import JsonFilePrefetchCache
from app.modules.scraping.config import ScraperConfig
from app.modules.scraping.llm import LLMProjectClassifier
from app.modules.scraping.service import PreScraperService

HTML = """
<html>
  <head><title>Constructora Demo</title></head>
  <body>
    <a href="/proyecto-alfa">Proyecto Alfa</a>
    <a href="/proyecto-beta">Proyecto Beta</a>
    <a href="/simulador">Simulador de Crédito</a>
  </body>
</html>
"""


def _indexed_body(cards: list[dict]) -> dict:
    return {str(i): card for i, card in enumerate(cards, start=1)}


def _html_transport(handler):
    return httpx.MockTransport(handler)


def _completions_response(cards: list[dict]) -> httpx.Response:
    body = {
        "choices": [
            {"message": {"content": json.dumps(cards, ensure_ascii=False)}}
        ]
    }
    return httpx.Response(200, json=body)


@pytest.mark.anyio
async def test_service_collapses_to_deterministic_fallback(tmp_path):
    """Task 6.5: LLM failure -> deterministic items, no 5xx, additive fields None."""
    def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    def llm_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream")

    async with httpx.AsyncClient(
        transport=_html_transport(html_handler)
    ) as mock_client:
        classifier = LLMProjectClassifier(
            api_key="test-key",
            model="deepseek/deepseek-v4-flash-0731:free",
            transport=httpx.MockTransport(llm_handler),
        )
        cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
        service = PreScraperService(
            config=ScraperConfig(),
            cache=cache,
            client=mock_client,
            classifier=classifier,
        )
        result = await service.pre_scrape("https://demo.example/proyectos")

    assert result.source == "live"
    assert result.filtered_out == 0
    assert len(result.items) == 3  # nothing dropped, deterministic pass-through
    for item in result.items:
        assert item.is_active_project is None
        assert item.status_badge is None
        assert item.price_from is None


@pytest.mark.anyio
async def test_service_without_classifier_works_unchanged(tmp_path):
    """Task 6.6: no API key configured -> pure deterministic path, no LLM."""
    def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    async with httpx.AsyncClient(
        transport=_html_transport(html_handler)
    ) as mock_client:
        cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
        service = PreScraperService(
            config=ScraperConfig(),
            cache=cache,
            client=mock_client,
            classifier=None,
        )
        result = await service.pre_scrape("https://demo.example/proyectos")

    assert result.source == "live"
    assert result.filtered_out == 0
    assert [i.title for i in result.items] == [
        "Proyecto Alfa",
        "Proyecto Beta",
        "Simulador de Crédito",
    ]
    assert result.items[0].is_active_project is None


@pytest.mark.anyio
async def test_service_maps_additive_fields_and_filters(tmp_path):
    """Task 6.7: classifier output maps onto items and drops non-projects."""
    def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    def llm_handler(request: httpx.Request) -> httpx.Response:
        return _completions_response(
            _indexed_body(
                [
                    {"is_project": True, "is_active_project": True, "title": "Proyecto Alfa",
                     "status_badge": "Preventa", "score": 90},
                    {"is_project": True, "is_active_project": False, "title": "Proyecto Beta",
                     "status_badge": "Agotado", "score": 80},
                    {"is_project": False, "is_active_project": False, "title": "Simulador de Crédito",
                     "status_badge": "Desconocido", "score": 5},
                ]
            )
        )

    async with httpx.AsyncClient(
        transport=_html_transport(html_handler)
    ) as mock_client:
        classifier = LLMProjectClassifier(
            api_key="test-key",
            model="deepseek/deepseek-v4-flash-0731:free",
            transport=httpx.MockTransport(llm_handler),
        )
        cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
        service = PreScraperService(
            config=ScraperConfig(),
            cache=cache,
            client=mock_client,
            classifier=classifier,
        )
        result = await service.pre_scrape("https://demo.example/proyectos")

    assert result.source == "live"
    assert result.filtered_out == 1  # "Simulador de Crédito" dropped
    assert [i.title for i in result.items] == ["Proyecto Alfa", "Proyecto Beta"]
    alfa = result.items[0]
    assert alfa.is_active_project is True
    assert alfa.status_badge == "Preventa"


@pytest.mark.anyio
async def test_service_all_items_filtered_returns_empty_200(tmp_path):
    """Task 6.12: everything filtered out -> 200 with empty items + filtered_out."""
    def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    def llm_handler(request: httpx.Request) -> httpx.Response:
        return _completions_response(
            _indexed_body(
                [
                    {"is_project": False, "is_active_project": False, "title": "Proyecto Alfa",
                     "status_badge": "Desconocido", "score": 5},
                    {"is_project": False, "is_active_project": False, "title": "Proyecto Beta",
                     "status_badge": "Desconocido", "score": 5},
                    {"is_project": False, "is_active_project": False, "title": "Simulador de Crédito",
                     "status_badge": "Desconocido", "score": 5},
                ]
            )
        )

    async with httpx.AsyncClient(
        transport=_html_transport(html_handler)
    ) as mock_client:
        classifier = LLMProjectClassifier(
            api_key="test-key",
            model="deepseek/deepseek-v4-flash-0731:free",
            transport=httpx.MockTransport(llm_handler),
        )
        cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
        service = PreScraperService(
            config=ScraperConfig(),
            cache=cache,
            client=mock_client,
            classifier=classifier,
        )
        result = await service.pre_scrape("https://demo.example/proyectos")

    assert result.source == "live"
    assert result.items == []
    assert result.filtered_out == 3


@pytest.mark.anyio
async def test_endpoint_contract_meta_and_additive_fields(tmp_path):
    """The HTTP response exposes `meta` only when items are filtered, and the
    additive LLM fields are present on the kept items."""
    from app.main import create_app

    def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    def llm_handler(request: httpx.Request) -> httpx.Response:
        return _completions_response(
            _indexed_body(
                [
                    {"is_project": True, "is_active_project": True,
                     "title": "Proyecto Alfa", "status_badge": "Preventa", "score": 90},
                    {"is_project": False, "is_active_project": False,
                     "title": "Proyecto Beta", "status_badge": "Desconocido", "score": 5},
                    {"is_project": False, "is_active_project": False,
                     "title": "Simulador de Crédito", "status_badge": "Desconocido", "score": 5},
                ]
            )
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(html_handler)
    ) as mock_client:
        classifier = LLMProjectClassifier(
            api_key="test-key",
            model="deepseek/deepseek-v4-flash-0731:free",
            transport=httpx.MockTransport(llm_handler),
        )
        cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
        service = PreScraperService(
            config=ScraperConfig(),
            cache=cache,
            client=mock_client,
            classifier=classifier,
        )
        app = create_app(pre_scraper=service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            response = await http.post(
                "/api/v1/scraping/pre-scrape",
                json={"url": "https://demo.example/proyectos"},
            )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Proyecto Alfa"
    assert items[0]["is_active_project"] is True
    assert items[0]["status_badge"] == "Preventa"
    assert response.json()["meta"] == {"filtered_out": 2}


@pytest.mark.anyio
async def test_endpoint_omits_meta_when_nothing_filtered(tmp_path):
    """No filtered items -> `meta` is absent from the payload (clean contract)."""
    from app.main import create_app

    def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    def llm_handler(request: httpx.Request) -> httpx.Response:
        return _completions_response(
            _indexed_body(
                [
                    {"is_project": True, "is_active_project": True,
                     "title": "Proyecto Alfa", "status_badge": "Preventa", "score": 90},
                    {"is_project": True, "is_active_project": True,
                     "title": "Proyecto Beta", "status_badge": "Entrega Inmediata", "score": 80},
                    {"is_project": True, "is_active_project": False,
                     "title": "Simulador de Crédito", "status_badge": "Agotado", "score": 70},
                ]
            )
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(html_handler)
    ) as mock_client:
        classifier = LLMProjectClassifier(
            api_key="test-key",
            model="deepseek/deepseek-v4-flash-0731:free",
            transport=httpx.MockTransport(llm_handler),
        )
        cache = JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False)
        service = PreScraperService(
            config=ScraperConfig(),
            cache=cache,
            client=mock_client,
            classifier=classifier,
        )
        app = create_app(pre_scraper=service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            response = await http.post(
                "/api/v1/scraping/pre-scrape",
                json={"url": "https://demo.example/proyectos"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"] is None
    assert len(body["items"]) == 3
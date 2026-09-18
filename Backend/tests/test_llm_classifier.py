"""LLM classifier tests: mock OpenRouter harness and batch contract (D2/D3).

Task 6.9 guarantees the whole suite uses ``httpx.MockTransport`` (zero real
calls, zero token consumption); task 6.2 asserts one batch call per request.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.modules.scraping.llm import LLMProjectClassifier
from app.modules.scraping.schemas import ProjectItem


def _items(n: int = 3) -> list[ProjectItem]:
    return [
        ProjectItem(id=i, title=f"Proyecto {i}", url=f"https://ejemplo.test/p{i}", source="card")
        for i in range(1, n + 1)
    ]


def _completions_response(cards: list[dict]) -> httpx.Response:
    body = {
        "choices": [{"message": {"content": json.dumps(cards, ensure_ascii=False)}}]
    }
    return httpx.Response(200, json=body)


def _indexed_body(cards: list[dict]) -> dict:
    return {str(i): card for i, card in enumerate(cards, start=1)}


def _classifier(handler) -> LLMProjectClassifier:
    transport = httpx.MockTransport(handler)
    return LLMProjectClassifier(
        api_key="test-key",
        model="deepseek/deepseek-v4-flash-0731:free",
        transport=transport,
        timeout=1.0,
    )


@pytest.mark.anyio
async def test_mock_transport_never_hits_real_network():
    """Task 6.9: the classifier routes every call through MockTransport."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _completions_response(
            _indexed_body(
                [
                    {"is_project": True, "is_active_project": True, "title": "Proyecto 1",
                     "status_badge": "Preventa", "score": 90},
                    {"is_project": True, "is_active_project": False, "title": "Proyecto 2",
                     "status_badge": "Agotado", "score": 80},
                    {"is_project": False, "is_active_project": False, "title": "Blog",
                     "status_badge": "Desconocido", "score": 10},
                ]
            )
        )

    classifier = _classifier(handler)
    cards = await classifier.classify(_items(3))
    await classifier.aclose()

    assert len(calls) == 1
    assert calls[0].url.host == "openrouter.ai"
    assert calls[0].headers["Authorization"] == "Bearer test-key"
    assert len(cards) == 3
    assert cards[0].is_project is True
    assert cards[2].is_project is False


@pytest.mark.anyio
async def test_single_batch_call_never_per_candidate():
    """Task 6.2: one LLM call classifies up to 10 candidates."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = json.loads(request.content)
        assert payload.get("response_format") == {"type": "json_object"}
        return _completions_response(
            _indexed_body(
                [
                    {"is_project": True, "is_active_project": True, "title": f"Proyecto {i}",
                     "status_badge": "Desconocido", "score": 85}
                    for i in range(1, 11)
                ]
            )
        )

    classifier = _classifier(handler)
    cards = await classifier.classify(_items(10))
    await classifier.aclose()

    assert len(calls) == 1
    assert len(cards) == 10


@pytest.mark.anyio
async def test_invalid_schema_returns_none_without_raw_content():
    """Task 6.3: a response that fails schema validation collapses to fallback."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = {"choices": [{"message": {"content": '{"1": {"nope": 1}}'}}]}
        return httpx.Response(200, json=body)

    classifier = _classifier(handler)
    cards = await classifier.classify(_items(3))
    await classifier.aclose()

    assert cards is None
    assert len(calls) == 1


@pytest.mark.anyio
async def test_misaligned_batch_length_returns_none():
    """Task 6.11: a response with a different length than the candidates falls back."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _completions_response(
            _indexed_body(
                [
                    {"is_project": True, "is_active_project": True, "title": "Proyecto 1",
                     "status_badge": "Desconocido", "score": 90}
                ]
            )
        )

    classifier = _classifier(handler)
    cards = await classifier.classify(_items(3))
    await classifier.aclose()

    assert cards is None
    assert len(calls) == 1


@pytest.mark.anyio
async def test_timeout_collapses_to_fallback():
    """Task 6.4: a provider that stalls triggers the hard wall-clock fallback.

    The transport sleeps far longer than ``timeout``; ``anyio.fail_after`` must
    abort the call and the classifier must collapse to ``None`` (fallback),
    never propagate and never wait for the slow provider.
    """
    import time

    import anyio

    class StallingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            await anyio.sleep(1.0)
            raise AssertionError("the hard timeout must abort before this point")

    classifier = LLMProjectClassifier(
        api_key="test-key",
        model="deepseek/deepseek-v4-flash-0731:free",
        transport=StallingTransport(),
        timeout=0.1,
    )
    started = time.perf_counter()
    cards = await classifier.classify(_items(1))
    elapsed = time.perf_counter() - started
    await classifier.aclose()

    assert cards is None
    assert elapsed < 0.5, f"hard timeout did not fire (took {elapsed:.2f}s)"


@pytest.mark.anyio
async def test_provider_http_error_returns_none():
    """Task 6.5: a non-2xx provider response collapses to fallback, never a 5xx."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, text="upstream unavailable")

    classifier = _classifier(handler)
    cards = await classifier.classify(_items(2))
    await classifier.aclose()

    assert cards is None
    assert len(calls) == 1


@pytest.mark.anyio
async def test_prompt_forbids_price_hallucination():
    """The system prompt must not let the model invent prices (anti-hallucination).

    Guardrails dressed as a test: the instructional text explicitly requires
    ``price_from`` to be null when the HTML shows no price.
    """
    from app.modules.scraping.llm import SYSTEM_PROMPT

    assert "NUNCA inventes ni infierras precios" in SYSTEM_PROMPT
    assert "price_from" in SYSTEM_PROMPT
    """A plain array (models ignoring the keyed shape) still aligns 1:1."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _completions_response(
            [
                {"is_project": True, "is_active_project": True, "title": "Proyecto 1",
                 "status_badge": "Desconocido", "score": 90},
                {"is_project": True, "is_active_project": False, "title": "Proyecto 2",
                 "status_badge": "Desconocido", "score": 70},
            ]
        )

    classifier = _classifier(handler)
    cards = await classifier.classify(_items(2))
    await classifier.aclose()

    assert len(cards) == 2
    assert cards[0].title == "Proyecto 1"
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
            [
                {"is_project": True, "is_active_project": True, "title": "Proyecto 1",
                 "status_badge": "Preventa", "score": 90},
                {"is_project": True, "is_active_project": False, "title": "Proyecto 2",
                 "status_badge": "Agotado", "score": 80},
                {"is_project": False, "is_active_project": False, "title": "Blog",
                 "status_badge": "Desconocido", "score": 10},
            ]
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
        user_message = payload["messages"][1]["content"]
        assert payload.get("response_format") == {"type": "json_object"}
        return _completions_response(
            [
                {"is_project": True, "is_active_project": True, "title": f"Proyecto {i}",
                 "status_badge": "Desconocido", "score": 85}
                for i in range(1, 11)
            ]
        )

    classifier = _classifier(handler)
    cards = await classifier.classify(_items(10))
    await classifier.aclose()

    assert len(calls) == 1
    assert len(cards) == 10
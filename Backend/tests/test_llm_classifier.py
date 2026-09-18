"""LLM classifier tests: mock OpenRouter harness, batch contract and timeouts.

Task 6.9 guarantees the whole suite uses ``httpx.MockTransport`` (zero real
calls, zero token consumption); task 6.2 asserts one batch call per request.
Task 6.13 pins the real OpenRouter payload shapes captured from live probes.
"""

from __future__ import annotations

import json
import pathlib
import time

import anyio
import httpx
import pytest

from app.modules.scraping.llm import (
    LLMProjectClassifier,
    ProjectCard,
    _extract_json_payload,
)
from app.modules.scraping.schemas import ProjectItem

GOLDEN_DIR = pathlib.Path(__file__).parent / "fixtures" / "scraping" / "golden"
RAW_INDEXED = GOLDEN_DIR / "raw_openrouter_response.json"
RAW_ARRAY = GOLDEN_DIR / "raw_openrouter_response_array.json"


def _items(n: int = 3) -> list[ProjectItem]:
    return [
        ProjectItem(id=i, title=f"Proyecto {i}", url=f"https://ejemplo.test/p{i}", source="card")
        for i in range(1, n + 1)
    ]


def _content_response(content: str) -> httpx.Response:
    body = {"choices": [{"message": {"content": content}}]}
    return httpx.Response(200, json=body)


def _completions_response(cards: list[dict]) -> httpx.Response:
    return _content_response(json.dumps(cards, ensure_ascii=False))


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


# --------------------------------------------------------------------------- #
# Real contract fixtures (task 6.13)
# --------------------------------------------------------------------------- #


def test_contract_parses_both_real_formats():
    """Task 6.13: the parser accepts the indexed object AND a plain array.

    ``raw_openrouter_response.json`` is the EXACT string returned by OpenRouter
    (``response_format=json_object``), including its leading space;
    ``raw_openrouter_response_array.json`` is the same three cards as a
    top-level array (defensive shape for providers that ignore ``json_object``).
    """
    indexed_str = RAW_INDEXED.read_text(encoding="utf-8")
    array_str = RAW_ARRAY.read_text(encoding="utf-8")

    assert indexed_str.lstrip().startswith("{"), "indexed fixture is not an object"
    assert array_str.lstrip().startswith("["), "array fixture is not an array"

    indexed_cards = [
        ProjectCard.model_validate(c) for c in _extract_json_payload(indexed_str)
    ]
    array_cards = [
        ProjectCard.model_validate(c) for c in _extract_json_payload(array_str)
    ]

    assert [c.model_dump() for c in indexed_cards] == [
        c.model_dump() for c in array_cards
    ]
    assert [c.is_project for c in indexed_cards] == [True, False, True]
    assert indexed_cards[2].status_badge == "Preventa"
    assert indexed_cards[2].score == 100


@pytest.mark.anyio
async def test_contract_classify_accepts_both_real_formats():
    """Task 6.13 (end-to-end): both real payloads align 1:1 through the client."""
    for raw in (
        RAW_INDEXED.read_text(encoding="utf-8"),
        RAW_ARRAY.read_text(encoding="utf-8"),
    ):
        classifier = _classifier(lambda request, raw=raw: _content_response(raw))
        cards = await classifier.classify(_items(3))
        await classifier.aclose()

        assert cards is not None, "the real payload must align with 3 candidates"
        assert len(cards) == 3
        assert [c.is_project for c in cards] == [True, False, True]


# --------------------------------------------------------------------------- #
# Mock harness and batch contract
# --------------------------------------------------------------------------- #


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
async def test_plain_array_payload_is_accepted_as_backup():
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


# --------------------------------------------------------------------------- #
# Fallback paths
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_invalid_schema_returns_none_without_raw_content():
    """Task 6.3: an invalid answer in the REAL indexed format collapses to fallback.

    Starts from the exact OpenRouter payload and corrupts ``status_badge`` so it
    no longer validates against ``ProjectCard``.
    """
    calls: list[httpx.Request] = []
    corrupted = RAW_INDEXED.read_text(encoding="utf-8").replace(
        '"Desconocido"', '"Estado Inexistente"'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _content_response(corrupted)

    classifier = _classifier(handler)
    cards = await classifier.classify(_items(3))
    await classifier.aclose()

    assert cards is None
    assert len(calls) == 1


@pytest.mark.anyio
async def test_misaligned_batch_length_returns_none():
    """Task 6.11: the REAL indexed payload with a dropped key falls back.

    The fixture has keys 1..3; removing one yields a 2-card answer for 3
    candidates, which must be rejected as misaligned (no partial assignment).
    """
    calls: list[httpx.Request] = []
    payload = json.loads(RAW_INDEXED.read_text(encoding="utf-8"))
    payload.pop("3")
    misaligned = json.dumps(payload, ensure_ascii=False)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _content_response(misaligned)

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


class _SlowDripStream(httpx.AsyncByteStream):
    """Streams the payload one chunk at a time, sleeping between chunks.

    This mimics a provider that sends response headers immediately and bytes
    slowly, which defeats httpx's per-read timeout (each chunk resets it).
    ``closed`` flips to True when the stream is torn down, proving the client
    was released after ``anyio.fail_after`` cancelled the call.
    """

    def __init__(self, chunk: bytes, delay: float, chunks: int) -> None:
        self._chunk = chunk
        self._delay = delay
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self):
        try:
            for _ in range(self._chunks):
                await anyio.sleep(self._delay)
                yield self._chunk
        finally:
            self.closed = True

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    "timeout,drop_delay,lo,hi",
    [
        (0.5, 0.05, 0.5, 1.0),
        (0.25, 0.025, 0.25, 0.5),
    ],
)
@pytest.mark.anyio
async def test_slow_drip_response_aborted_by_hard_timeout(timeout, drop_delay, lo, hi):
    """Slow-drip guard: ``anyio.fail_after`` interrupts and releases the stream.

    httpx's own timeout is per read-gap, so a response trickling bytes would keep
    it alive past the cap. The wall-clock ``anyio.fail_after(timeout)`` must abort
    the call, collapse to the deterministic fallback and close the stream. Drips
    fast (<=50ms) so each scenario runs in well under a second.
    """
    stream = _SlowDripStream(
        chunk=b'{"choices": [{"message": {"content": "x"}}]}',
        delay=drop_delay,
        chunks=int(timeout / drop_delay * 20) + 1,  # ~20x the cap in drip time
    )

    class DripTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=stream,
            )

    classifier = LLMProjectClassifier(
        api_key="test-key",
        model="deepseek/deepseek-v4-flash-0731:free",
        transport=DripTransport(),
        timeout=timeout,
    )
    started = time.perf_counter()
    cards = await classifier.classify(_items(1))
    elapsed = time.perf_counter() - started
    await classifier.aclose()

    assert cards is None, "slow-drip response must collapse to fallback"
    assert lo <= elapsed < hi, f"hard timeout fired off-target ({elapsed:.3f}s)"
    assert stream.closed is True, "the drip stream must be released after abort"


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

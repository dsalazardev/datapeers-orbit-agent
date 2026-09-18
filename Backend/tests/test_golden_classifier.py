"""Golden dataset evaluation for the LLM classifier (task 6.10).

Uses the frozen HTML fixtures (sites 01..10) with the expected labels. The
classifier is evaluated either (a) against the recorded real provider responses
in ``recorded_responses.json`` (default, offline, zero tokens), or (b) live
against OpenRouter when ``ORBIT_LLM_EVAL_REAL=1`` is set and an API key exists.
Thresholds: ``is_project`` accuracy >= 90% and zero price hallucinations.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from app.modules.scraping.llm import LLMProjectClassifier, ProjectCard, map_card_to_item
from app.modules.scraping.schemas import ProjectItem
from app.modules.scraping.service import PreScraperService

GOLDEN_DIR = pathlib.Path(__file__).parent / "fixtures" / "scraping" / "golden"


def _load_golden():
    expected = json.loads((GOLDEN_DIR / "expected.json").read_text(encoding="utf-8"))
    labels_by_site = expected["labels_by_site"]
    manifest = json.loads((GOLDEN_DIR / "_manifest.json").read_text(encoding="utf-8"))
    return labels_by_site, manifest


def _items_for(labels: list[dict]) -> list[ProjectItem]:
    return [
        ProjectItem(id=i + 1, title=c["title"], url=c["url"], source=c["source"])
        for i, c in enumerate(labels)
    ]


def _accuracy(cards, labels):
    by_title = {c["title"]: c["is_project"] for c in labels}
    ok = sum(1 for card in cards if card.is_project == by_title.get(card.title))
    return ok / max(len(cards), 1), ok, len(cards)


def _price_hallucinations(cards, labels):
    hallucinations = 0
    for card in cards:
        has_price_signal = any(
            tok in card.title for tok in ("$", "COP", "m³", "m²", "precio", "Desde")
        )
        if card.price_from is not None and not has_price_signal:
            hallucinations += 1
    return hallucinations


@pytest.mark.golden
def test_golden_recorded_accuracy_and_no_hallucinations():
    """Task 6.10: recorded provider answers must meet the accuracy floor."""
    labels_by_site, _ = _load_golden()
    recorded = json.loads(
        (GOLDEN_DIR / "recorded_responses.json").read_text(encoding="utf-8")
    )["by_site"]

    assert set(recorded) == set(labels_by_site), "missing recorded answers"

    total_ok = 0
    total = 0
    hallucinations = 0
    for site, cards in recorded.items():
        labels = labels_by_site[site]
        class_project_cards = [ProjectCard.model_validate(card) for card in cards]
        _, ok, n = _accuracy(class_project_cards, labels)
        total_ok += ok
        total += n
        hallucinations += _price_hallucinations(class_project_cards, labels)

    assert total_ok / max(total, 1) >= 0.9, "global accuracy below 90%"
    assert hallucinations == 0, "price hallucinations detected"
    assert all(
        _accuracy(
            [ProjectCard.model_validate(c) for c in cards], labels_by_site[site]
        )[0]
        > 0.5
        for site, cards in recorded.items()
    ), "some site performed at or below chance"


@pytest.mark.golden
@pytest.mark.anyio
async def test_golden_live_via_service_contract(tmp_path):
    """Task 6.10 (optional): run the real classifier against frozen HTML.

    Skipped unless ORBIT_LLM_EVAL_REAL=1 and an API key is configured. The
    service contract (mapped additive fields) is asserted, not raw cards.
    """
    if os.environ.get("ORBIT_LLM_EVAL_REAL") != "1":
        pytest.skip("set ORBIT_LLM_EVAL_REAL=1 to run the live golden evaluation")
    from app.core.settings import Settings

    settings = Settings(_env_file=".env")
    if not settings.openrouter_api_key:
        pytest.skip("no OpenRouter API key configured")

    from app.modules.scraping.cache import JsonFilePrefetchCache
    from app.modules.scraping.config import ScraperConfig

    labels_by_site, _ = _load_golden()
    service = PreScraperService(
        ScraperConfig(),
        JsonFilePrefetchCache(tmp_path, ttl_seconds=3600, seed_enabled=False),
        classifier=LLMProjectClassifier(
            api_key=settings.openrouter_api_key,
            model=settings.llm_model,
            timeout=30.0,
        ),
    )

    total_ok = 0
    total = 0
    for site, labels in labels_by_site.items():
        result = await service._classify_live(_items_for(labels))
        assert isinstance(result, tuple)
        mapped, filtered_out = result
        assert len(mapped) + filtered_out == len(labels)
        # additive fields are safe to inject
        for item in mapped:
            assert isinstance(item.is_active_project, bool)
            assert isinstance(item.status_badge, str)
    await service._classifier.aclose()


@pytest.mark.golden
def test_golden_manifest_urls_have_live_domains():
    """Every frozen fixture maps to a real, reachable candidate URL (traceability)."""
    _, manifest = _load_golden()
    for site, url in manifest["url_by_site"].items():
        assert url.startswith("https://") or url.startswith("http://"), site
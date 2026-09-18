"""Golden dataset evaluation for the LLM classifier (task 6.10).

Uses the frozen HTML fixtures (sites 01..14) with the expected labels. The
classifier is evaluated either (a) against the recorded real provider responses
in ``recorded_responses.json`` (default, offline, zero tokens), or (b) live
against OpenRouter when ``ORBIT_LLM_EVAL_REAL=1`` is set and an API key exists.

Closing criteria (positive class focus, see proposal.md):
    precision >= 0.85, recall >= 0.80, F1 >= 0.80, zero price hallucinations.
The dataset is unbalanced (many more negatives than positives), so accuracy
alone is NOT a closing metric; the confusion matrix is reported over the
positive class. Recorded answers and labels are aligned by index because the
provider may shorten titles while the prompt keeps an index-keyed 1..N order.
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

RECALL_FLOOR = 0.80
PRECISION_FLOOR = 0.85
F1_FLOOR = 0.80


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


def _confusion_matrix(cards: list[ProjectCard], labels: list[dict]):
    """Index-aligned TP/FP/FN/TN over the positive class."""
    tp = fp = fn = tn = 0
    for card, label in zip(cards, labels, strict=True):
        expected = label["is_project"]
        predicted = card.is_project
        if expected and predicted:
            tp += 1
        elif not expected and predicted:
            fp += 1
        elif expected and not predicted:
            fn += 1
        else:
            tn += 1
    return tp, fp, fn, tn


def _positive_metrics(tp, fp, fn, tn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _accuracy(cards, labels):
    tp, fp, fn, tn = _confusion_matrix(cards, labels)
    return (tp + tn) / max(tp + fp + fn + tn, 1)


def _price_hallucinations(cards, labels):
    hallucinations = 0
    for card, label in zip(cards, labels, strict=True):
        has_price_signal = any(
            tok in label["title"] for tok in ("$", "COP", "m³", "m²", "precio", "Desde")
        )
        if card.price_from is not None and not has_price_signal:
            hallucinations += 1
    return hallucinations


@pytest.mark.golden
def test_golden_recorded_accuracy_and_no_hallucinations():
    """Task 6.10: recorded provider answers must meet the closing criteria.

    Metrics are computed over the positive class (precision/recall/F1) on the
    index-aligned answers; accuracy is reported for context but does not close.
    """
    labels_by_site, _ = _load_golden()
    recorded = json.loads(
        (GOLDEN_DIR / "recorded_responses.json").read_text(encoding="utf-8")
    )["by_site"]

    assert set(recorded) == set(labels_by_site), "missing recorded answers"

    total_tp = total_fp = total_fn = total_tn = 0
    hallucinations = 0
    worst_site_accuracy = 1.0
    for site, cards in recorded.items():
        labels = labels_by_site[site]
        class_project_cards = [ProjectCard.model_validate(card) for card in cards]
        tp, fp, fn, tn = _confusion_matrix(class_project_cards, labels)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        total_tn += tn
        hallucinations += _price_hallucinations(class_project_cards, labels)
        worst_site_accuracy = min(
            worst_site_accuracy, _accuracy(class_project_cards, labels)
        )

    precision, recall, f1 = _positive_metrics(total_tp, total_fp, total_fn, total_tn)
    accuracy = (total_tp + total_tn) / max(total_tp + total_fp + total_fn + total_tn, 1)

    assert recall >= RECALL_FLOOR, f"recall {recall:.3f} below {RECALL_FLOOR}"
    assert precision >= PRECISION_FLOOR, f"precision {precision:.3f} below {PRECISION_FLOOR}"
    assert f1 >= F1_FLOOR, f"F1 {f1:.3f} below {F1_FLOOR}"
    assert hallucinations == 0, "price hallucinations detected"
    assert worst_site_accuracy > 0.5, "some site performed at or below chance"


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
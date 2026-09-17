"""N1 and application-level tests: scheduling without inline execution.

Covers ORB-FR-023 (partial: background start and non-blocking) and design
D11-N1. The scheduler double records jobs but never executes them, so the
assertions are causal and do not depend on timing.
"""

from __future__ import annotations

import pytest

from app.modules.ingestion.application.runner import SkeletonIngestionPipeline
from app.modules.ingestion.application.use_cases import StartUrlIngestion
from app.modules.ingestion.domain.errors import UrlRejected
from app.modules.ingestion.domain.models import OnboardingState, OnboardingStatus
from app.modules.ingestion.infrastructure.store import InMemoryOnboardingStateStore
from tests.doubles import FakeHostResolver, RecordingPipeline, RecordingScheduler


def _composition(addresses=None, error=None):
    store = InMemoryOnboardingStateStore()
    pipeline = RecordingPipeline()
    use_case = StartUrlIngestion(
        store=store,
        resolver=FakeHostResolver(
            addresses=addresses if addresses is not None else ["93.184.216.34"],
            error=error,
        ),
        pipeline=pipeline,
    )
    return use_case, store, pipeline


@pytest.mark.anyio
async def test_use_case_returns_without_executing_the_pipeline():
    """ORB-FR-023 — the pipeline is scheduled, never executed, during the request."""
    use_case, store, pipeline = _composition()
    scheduler = RecordingScheduler()

    state = await use_case.handle("https://example.com", "req-1", scheduler)

    assert state.status == OnboardingStatus.RECEIVED
    assert str(state.primary_route) == "url_scraping"
    assert [str(route) for route in state.secondary_routes] == ["pdf", "brochure"]
    assert pipeline.calls == []
    assert len(scheduler.jobs) == 1
    assert store.get(state.onboarding_id) is state


@pytest.mark.anyio
async def test_use_case_rejects_url_resolving_to_blocked_address():
    """ORB-TK-01 criterion 1 — a host that resolves internal is rejected."""
    use_case, store, _ = _composition(addresses=["10.0.0.8"])
    with pytest.raises(UrlRejected) as exc_info:
        await use_case.handle("https://intranet.example", "req-2", RecordingScheduler())
    assert exc_info.value.reason_code == "address_not_allowed"
    assert store._states == {}


@pytest.mark.anyio
async def test_use_case_maps_dns_errors_to_resolution_failure():
    """ORB-TK-01 criterion 1 — timeout/empty DNS become dns_resolution_failed."""
    use_case, _, _ = _composition(error="timeout")
    with pytest.raises(UrlRejected) as exc_info:
        await use_case.handle("https://slow.example", "req-3", RecordingScheduler())
    assert exc_info.value.reason_code == "dns_resolution_failed"


class AlternateStore:
    """Second implementation of the OnboardingStateStore port (design D11, D5)."""

    def __init__(self) -> None:
        self.items: dict = {}

    def save(self, state: OnboardingState) -> None:
        self.items[state.onboarding_id] = state

    def get(self, onboarding_id):
        return self.items.get(onboarding_id)


@pytest.mark.anyio
async def test_store_port_can_be_swapped_without_touching_the_use_case():
    """ORB-CON-015 — the store adapter is replaceable behind its port."""
    use_case, _, _ = _composition()
    alternate = AlternateStore()
    use_case.store = alternate

    state = await use_case.handle("https://example.com", "req-4", RecordingScheduler())

    assert alternate.get(state.onboarding_id) is state


@pytest.mark.anyio
async def test_skeleton_pipeline_marks_state_started():
    """ORB-FR-023 — the background work records its start in the onboarding state."""
    store = InMemoryOnboardingStateStore()
    pipeline = SkeletonIngestionPipeline(store)
    state = OnboardingState(source_url="https://example.com")
    store.save(state)

    await pipeline.run(state.onboarding_id)

    assert store.get(state.onboarding_id).status == OnboardingStatus.INGESTION_STARTED


@pytest.mark.anyio
async def test_skeleton_pipeline_marks_state_failed_on_error():
    """ORB-FR-023 — a failing background job leaves the state as failed."""

    class ExplodingPipeline(SkeletonIngestionPipeline):
        async def _work(self, onboarding_id):
            raise RuntimeError("boom")

    store = InMemoryOnboardingStateStore()
    pipeline = ExplodingPipeline(store)
    state = OnboardingState(source_url="https://example.com")
    store.save(state)

    await pipeline.run(state.onboarding_id)

    assert store.get(state.onboarding_id).status == OnboardingStatus.FAILED

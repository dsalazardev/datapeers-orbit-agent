"""Ports of the ingestion application layer (ORB-CON-015, ORB-NFR-008, ORB-NFR-013).

The domain and the use cases depend only on these protocols; concrete adapters
live under infrastructure/ and can be replaced without touching the core.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol, Sequence
from uuid import UUID

from app.modules.ingestion.domain.models import OnboardingState


class OnboardingStateStore(Protocol):
    def save(self, state: OnboardingState) -> None: ...

    def get(self, onboarding_id: UUID) -> OnboardingState | None: ...


class IngestionPipeline(Protocol):
    async def run(self, onboarding_id: UUID) -> None: ...


class IngestionScheduler(Protocol):
    def schedule(self, job: Callable[[], Awaitable[None]]) -> None: ...


class HostResolver(Protocol):
    async def resolve(self, host: str) -> Sequence[str]: ...

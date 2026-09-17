"""In-memory onboarding state store (provisional adapter).

TODO(ORB-INT-006): VOLATILE ADAPTER. State is lost when the process restarts
and is NOT shared across workers/processes. The definitive persistence adapter
(PostgreSQL/pgvector, pending ratification with datapeers) replaces this class
behind the same OnboardingStateStore port without touching the domain or the
use cases.
"""

from __future__ import annotations

import threading
from uuid import UUID

from app.modules.ingestion.domain.models import OnboardingState


class InMemoryOnboardingStateStore:
    def __init__(self) -> None:
        self._states: dict[UUID, OnboardingState] = {}
        self._lock = threading.Lock()

    def save(self, state: OnboardingState) -> None:
        with self._lock:
            self._states[state.onboarding_id] = state

    def get(self, onboarding_id: UUID) -> OnboardingState | None:
        with self._lock:
            return self._states.get(onboarding_id)

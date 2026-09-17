"""Skeleton ingestion pipeline (ORB-FR-023, partial coverage).

This adapter records the start of the background work, transitions the state to
`ingestion_started` and marks `failed` on unexpected errors. The detailed
scraping, the multithreaded parallelism and the user notification belong to
ORB-TK-02/ORB-TK-03 and are intentionally NOT implemented here.

When the real extraction lands, it MUST reuse the destination validation right
before every outbound request (design D7, DNS revalidation seam).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from app.modules.ingestion.application.ports import OnboardingStateStore

logger = logging.getLogger("orbit.ingestion")


@dataclass
class SkeletonIngestionPipeline:
    store: OnboardingStateStore

    async def run(self, onboarding_id: UUID) -> None:
        state = self.store.get(onboarding_id)
        if state is None:
            logger.error(
                "ingestion_state_missing",
                extra={"onboarding_id": str(onboarding_id)},
            )
            return

        state.mark_started()
        self.store.save(state)
        logger.info(
            "ingestion_started",
            extra={
                "onboarding_id": str(onboarding_id),
                "request_id": state.request_id,
            },
        )
        try:
            await self._work(onboarding_id)
        except Exception:
            state.mark_failed()
            self.store.save(state)
            logger.exception(
                "ingestion_failed",
                extra={
                    "onboarding_id": str(onboarding_id),
                    "request_id": state.request_id,
                },
            )

    async def _work(self, onboarding_id: UUID) -> None:
        """Seam for the ORB-TK-02/ORB-TK-03 detailed scraping (no-op for now)."""
        return None

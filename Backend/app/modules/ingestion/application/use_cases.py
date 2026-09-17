"""Ingestion use cases.

`StartUrlIngestion` orchestrates validation, DNS verification, state
persistence and the non-blocking scheduling of the pipeline (ORB-FR-002,
ORB-FR-005, ORB-FR-023, ORB-NFR-017). The use case never executes the pipeline
inline: it hands the work to the IngestionScheduler port.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from uuid import UUID

from app.modules.ingestion.application.ports import (
    HostResolver,
    IngestionPipeline,
    IngestionScheduler,
    OnboardingStateStore,
)
from app.modules.ingestion.domain.errors import DnsResolutionError, UrlRejected
from app.modules.ingestion.domain.models import OnboardingState
from app.modules.ingestion.domain.validation import (
    ensure_all_addresses_allowed,
    parse_target,
)

logger = logging.getLogger("orbit.ingestion")


@dataclass
class StartUrlIngestion:
    store: OnboardingStateStore
    resolver: HostResolver
    pipeline: IngestionPipeline

    async def handle(
        self, raw_url: str, request_id: str, scheduler: IngestionScheduler
    ) -> OnboardingState:
        target = parse_target(raw_url)
        addresses = await self._resolve_target(target.host)
        ensure_all_addresses_allowed(addresses)

        state = OnboardingState(source_url=target.url, request_id=request_id)
        self.store.save(state)
        scheduler.schedule(partial(self.pipeline.run, state.onboarding_id))
        logger.info(
            "ingestion_accepted",
            extra={
                "onboarding_id": str(state.onboarding_id),
                "request_id": request_id,
            },
        )
        return state

    async def _resolve_target(self, host: str) -> list[str]:
        try:
            return list(await self.resolver.resolve(host))
        except DnsResolutionError as exc:
            raise UrlRejected(
                "dns_resolution_failed", "The host could not be resolved."
            ) from exc


@dataclass
class GetOnboardingState:
    store: OnboardingStateStore

    def handle(self, onboarding_id: UUID) -> OnboardingState | None:
        return self.store.get(onboarding_id)

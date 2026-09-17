"""Pure domain model for the onboarding ingestion state.

Implements the state required by ORB-FR-004, ORB-FR-005 and ORB-INT-004: the
primary ingestion route is the site URL scraping, and PDF/brochure are declared
secondary routes. No framework dependencies live here (ORB-CON-003).

TODO(ORB-INT-006): this state is currently only held in memory by the
provisional store adapter; the definitive persistent adapter is pending
ratification with datapeers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4


class OnboardingStatus(StrEnum):
    RECEIVED = "received"
    INGESTION_STARTED = "ingestion_started"
    FAILED = "failed"


class IngestionRoute(StrEnum):
    URL_SCRAPING = "url_scraping"
    PDF = "pdf"
    BROCHURE = "brochure"


PRIMARY_ROUTE: IngestionRoute = IngestionRoute.URL_SCRAPING
SECONDARY_ROUTES: tuple[IngestionRoute, ...] = (
    IngestionRoute.PDF,
    IngestionRoute.BROCHURE,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class OnboardingState:
    """State of a prospect's onboarding ingestion."""

    source_url: str
    request_id: str = ""
    onboarding_id: UUID = field(default_factory=uuid4)
    primary_route: IngestionRoute = PRIMARY_ROUTE
    secondary_routes: tuple[IngestionRoute, ...] = SECONDARY_ROUTES
    status: OnboardingStatus = OnboardingStatus.RECEIVED
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def mark_started(self) -> None:
        self.status = OnboardingStatus.INGESTION_STARTED
        self.updated_at = utc_now()

    def mark_failed(self) -> None:
        self.status = OnboardingStatus.FAILED
        self.updated_at = utc_now()

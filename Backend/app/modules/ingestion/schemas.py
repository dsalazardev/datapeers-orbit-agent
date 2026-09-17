"""HTTP contracts for the ingestion endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateOnboardingRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class OnboardingStateResponse(BaseModel):
    onboarding_id: UUID
    source_url: str
    primary_route: str
    secondary_routes: list[str]
    status: str
    created_at: datetime
    updated_at: datetime


class ErrorDetail(BaseModel):
    reason_code: str
    message: str

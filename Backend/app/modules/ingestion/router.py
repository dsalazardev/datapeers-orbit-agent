"""HTTP adapter for the ingestion capability.

The router only translates HTTP into use cases and maps domain errors to safe
responses; no business logic lives here (ORB-CON-003).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from app.modules.ingestion.application.use_cases import (
    GetOnboardingState,
    StartUrlIngestion,
)
from app.modules.ingestion.domain.errors import UrlRejected
from app.modules.ingestion.domain.models import OnboardingState
from app.modules.ingestion.schemas import (
    CreateOnboardingRequest,
    OnboardingStateResponse,
)

logger = logging.getLogger("orbit.ingestion")

router = APIRouter(tags=["ingestion"])


def _to_response(state: OnboardingState) -> OnboardingStateResponse:
    return OnboardingStateResponse(
        onboarding_id=state.onboarding_id,
        source_url=state.source_url,
        primary_route=str(state.primary_route),
        secondary_routes=[str(route) for route in state.secondary_routes],
        status=str(state.status),
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


@router.post(
    "/onboardings",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=OnboardingStateResponse,
)
async def create_onboarding(
    payload: CreateOnboardingRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> OnboardingStateResponse:
    use_case: StartUrlIngestion = request.app.state.start_ingestion
    scheduler = request.app.state.scheduler_factory(background_tasks)
    request_id = getattr(request.state, "request_id", "-")
    try:
        state = await use_case.handle(payload.url, request_id, scheduler)
    except UrlRejected as exc:
        logger.warning(
            "url_rejected",
            extra={"reason_code": exc.reason_code, "request_id": request_id},
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"reason_code": exc.reason_code, "message": exc.message},
        ) from exc
    return _to_response(state)


@router.get("/onboardings/{onboarding_id}", response_model=OnboardingStateResponse)
async def get_onboarding(onboarding_id: UUID, request: Request) -> OnboardingStateResponse:
    use_case: GetOnboardingState = request.app.state.get_onboarding
    state = use_case.handle(onboarding_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "reason_code": "onboarding_not_found",
                "message": "The onboarding does not exist.",
            },
        )
    return _to_response(state)

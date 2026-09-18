from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.modules.scraping.errors import (
    HTTP_STATUS_BY_CODE,
    ScrapeError,
    ScrapeReasonCode,
    error_payload,
)
from app.modules.scraping.schemas import (
    PreScrapeRequest,
    PreScrapeResponse,
    ScrapeMeta,
)
from app.modules.scraping.service import PreScraperService

router = APIRouter(prefix="/scraping", tags=["scraping"])


@router.post("/pre-scrape", response_model=PreScrapeResponse)
async def pre_scrape(
    request: PreScrapeRequest, http_request: Request
) -> JSONResponse | PreScrapeResponse:
    service: PreScraperService | None = getattr(http_request.app.state, "pre_scraper", None)
    request_id = str(getattr(http_request.state, "request_id", "-"))
    if service is None:
        return _error_response(ScrapeError.for_code(ScrapeReasonCode.INTERNAL_ERROR), request_id)
    try:
        result = await service.pre_scrape(str(request.url), request.max_items)
    except ScrapeError as exc:
        return _error_response(exc, request_id)
    return PreScrapeResponse(
        url=request.url,
        items=result.items,
        truncated=result.truncated,
        meta=ScrapeMeta(filtered_out=result.filtered_out)
        if result.filtered_out > 0
        else None,
    )


def _error_response(error: ScrapeError, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=HTTP_STATUS_BY_CODE[error.reason_code],
        content=error_payload(error, request_id),
    )
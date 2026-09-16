from fastapi import APIRouter, HTTPException

from app.modules.scraping.schemas import PreScrapeRequest, PreScrapeResponse
from app.modules.scraping.services.pre_scraper import PreScrapeError, PreScraper

router = APIRouter(prefix="/scraping", tags=["scraping"])

_pre_scraper = PreScraper()


@router.post("/pre-scrape", response_model=PreScrapeResponse)
async def pre_scrape(request: PreScrapeRequest) -> PreScrapeResponse:
    try:
        items = await _pre_scraper.run(request)
    except PreScrapeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    truncated = len(items) == request.max_items
    return PreScrapeResponse(url=request.url, items=items, truncated=truncated)
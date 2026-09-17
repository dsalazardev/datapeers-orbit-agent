from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

MAX_ITEMS = 10


class PreScrapeRequest(BaseModel):
    url: HttpUrl
    max_items: int = Field(default=MAX_ITEMS, ge=1, le=MAX_ITEMS)


class ProjectItem(BaseModel):
    id: int
    title: str
    url: HttpUrl
    source: Literal["meta", "card", "link"]


class PreScrapeResponse(BaseModel):
    url: HttpUrl
    items: list[ProjectItem]
    truncated: bool
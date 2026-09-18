from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

MAX_ITEMS = 10

StatusBadge = Literal["Preventa", "Entrega Inmediata", "Agotado", "Desconocido"]


class PreScrapeRequest(BaseModel):
    url: HttpUrl
    max_items: int = Field(default=MAX_ITEMS, ge=1, le=MAX_ITEMS)


class ProjectItem(BaseModel):
    id: int
    title: str
    url: HttpUrl
    source: Literal["meta", "card", "link"]
    is_active_project: bool | None = None
    status_badge: StatusBadge | None = None
    price_from: str | None = None


class ScrapeMeta(BaseModel):
    filtered_out: int = 0


class PreScrapeResponse(BaseModel):
    url: HttpUrl
    items: list[ProjectItem]
    truncated: bool
    meta: ScrapeMeta | None = None
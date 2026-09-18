"""Pre-scraper orchestration: fetch -> parse (in thread) -> cache.

Implements the flow designed in D2/D3/D5:
  cache hit            -> serve immediately (source=cache)
  no cache + fetch ok  -> parse + persist (source=live)
  no cache + fetch bad -> seeded fallback (<200ms) or safe error

Only network waits and cache I/O suspend on the event loop; HTML parsing and
candidate extraction run in the anyio thread pool so 50 concurrent requests
never block `/health` (ORB-SCRAPE-001).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import anyio.to_thread
import httpx

from app.modules.scraping.cache import CacheEntry, JsonFilePrefetchCache
from app.modules.scraping.config import ScraperConfig
from app.modules.scraping.errors import ScrapeError, ScrapeReasonCode
from app.modules.scraping.parser import extract_candidates, parse_html
from app.modules.scraping.schemas import ProjectItem

logger = logging.getLogger("orbit.scraping")

FetchSource = Literal["cache", "seed", "live"]


class PreScrapeResult:
    __slots__ = ("items", "truncated", "source")

    def __init__(
        self,
        items: list[ProjectItem],
        truncated: bool,
        source: FetchSource,
    ) -> None:
        self.items = items
        self.truncated = truncated
        self.source = source


class PreScraperService:
    def __init__(
        self,
        config: ScraperConfig,
        cache: JsonFilePrefetchCache,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._cache = cache
        self._client = client

    async def pre_scrape(self, url: str, max_items: int = 10) -> PreScrapeResult:
        target = str(url)

        cached = await self._cache.get(target)
        if cached is not None and cached.items:
            return PreScrapeResult(
                items=self._build_items(cached),
                truncated=cached.truncated,
                source="cache",
            )

        try:
            html, body_truncated = await self._fetch(target)
        except httpx.HTTPError as exc:
            seed = await self._cache.get_seed(target)
            if seed is not None and seed.items:
                return PreScrapeResult(
                    items=self._build_items(seed),
                    truncated=False,
                    source="seed",
                )
            raise self._error_for_fetch(exc) from exc

        if not self._html_plausible(html):
            seed = await self._cache.get_seed(target)
            if seed is not None and seed.items:
                return PreScrapeResult(
                    items=self._build_items(seed),
                    truncated=False,
                    source="seed",
                )
            raise ScrapeError.for_code(ScrapeReasonCode.INVALID_RESPONSE)

        try:
            items, parsed_truncated = await self._parse(target, html)
        except ScrapeError:
            raise
        except Exception as exc:
            raise ScrapeError.for_code(ScrapeReasonCode.PARSE_FAILED) from exc
        truncated = body_truncated or parsed_truncated

        if not items:
            seed = await self._cache.get_seed(target)
            if seed is not None and seed.items:
                return PreScrapeResult(
                    items=self._build_items(seed),
                    truncated=False,
                    source="seed",
                )
            raise ScrapeError.for_code(ScrapeReasonCode.INVALID_RESPONSE)

        await self._cache.put(target, self._serialize_items(items), truncated)
        logger.info("pre_scrape_live", extra={"source": "live"})
        return PreScrapeResult(items=items[:max_items], truncated=truncated, source="live")

    async def _fetch(self, target: str) -> tuple[bytes, bool]:
        headers = self._config.request_headers
        timeout = self._config.request_timeout
        if self._client is not None:
            response = await self._client.get(
                target,
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            )
        else:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(target, headers=headers)
        response.raise_for_status()

        content = response.content
        truncated = content.__len__() > self._config.max_body_size
        return content[: self._config.max_body_size], truncated

    async def _parse(self, target: str, html: bytes) -> tuple[list[ProjectItem], bool]:
        soup = await anyio.to_thread.run_sync(parse_html, html, self._config)
        candidates = await anyio.to_thread.run_sync(
            extract_candidates, soup, target, self._config
        )
        items: list[ProjectItem] = []
        for index, (title, url, source) in enumerate(candidates, start=1):
            source = "link" if source == "grouping" else source
            items.append(
                ProjectItem(
                    id=index,
                    title=title,
                    url=url,
                    source=source,
                )
            )
        return items, False

    @staticmethod
    def _error_for_fetch(exc: httpx.HTTPError) -> ScrapeError:
        response = getattr(exc, "response", None)
        if response is not None and response.status_code in (401, 403, 429):
            return ScrapeError.for_code(ScrapeReasonCode.UPSTREAM_BLOCKED)
        return ScrapeError.for_code(ScrapeReasonCode.FETCH_FAILED)

    @staticmethod
    def _html_plausible(html: bytes) -> bool:
        sample = html.decode("utf-8", errors="ignore").strip()
        return sample.startswith("<") and "</html>" in sample.lower()

    @staticmethod
    def _build_items(entry: CacheEntry) -> list[ProjectItem]:
        items = []
        for raw in entry.items:
            raw = dict(raw)
            raw["url"] = str(raw["url"])
            items.append(ProjectItem(**raw))
        return items

    @staticmethod
    def _serialize_items(items: list[ProjectItem]) -> list[dict[str, Any]]:
        payload = []
        for item in items:
            ser = item.model_dump()
            ser["url"] = str(ser["url"])
            payload.append(ser)
        return payload
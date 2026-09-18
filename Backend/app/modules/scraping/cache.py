"""Local filesystem/JSON cache for pre-scrape results plus a seeded fallback.

Resilience for demos (ORB-SCRAPE-004): a hit serves cached items without
network; when fetch fails and no cache exists, a seeded entry answers instead
of breaking the demo. All disk I/O runs through ``anyio.to_thread`` so the
event loop stays free.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import anyio
import anyio.to_thread

logger = logging.getLogger("orbit.scraping")

CACHE_SCHEMA_VERSION = "v1"
SEED_FILENAME = "seed.json"


class CacheEntry:
    __slots__ = ("url", "items", "truncated", "cached_at")

    def __init__(
        self,
        url: str,
        items: list[dict[str, Any]],
        truncated: bool,
        cached_at: str,
    ) -> None:
        self.url = url
        self.items = items
        self.truncated = truncated
        self.cached_at = cached_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "items": self.items,
            "truncated": self.truncated,
            "cached_at": self.cached_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CacheEntry:
        return cls(
            url=str(data["url"]),
            items=list(data.get("items", [])),
            truncated=bool(data.get("truncated", False)),
            cached_at=str(data.get("cached_at", "")),
        )


def seed_key(url: str) -> str:
    """URL keys accepted in seed.json: exact URL or bare hostname."""
    return url


class JsonFilePrefetchCache:
    """One JSON file per URL under ``<cache_dir>/v1/<sha256(url)>.json``."""

    def __init__(
        self,
        cache_dir: str | Path,
        seed: Mapping[str, dict[str, Any]] | None = None,
        *,
        ttl_seconds: int = 3600,
        seed_enabled: bool = True,
    ) -> None:
        self._root = Path(cache_dir)
        self._v1 = self._root / CACHE_SCHEMA_VERSION
        self._ttl_seconds = ttl_seconds
        self._seed = dict(seed or {})
        self._seed_enabled = seed_enabled

    @classmethod
    def with_seed_file(
        cls,
        cache_dir: str | Path,
        seed_path: str | Path | None = None,
        *,
        ttl_seconds: int = 3600,
        seed_enabled: bool = True,
    ) -> JsonFilePrefetchCache:
        seed = load_seed_file(seed_path) if seed_path is not None else None
        return cls(
            cache_dir,
            seed=seed,
            ttl_seconds=ttl_seconds,
            seed_enabled=seed_enabled,
        )

    def _path_for(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._v1 / f"{digest}.json"

    async def get(self, url: str) -> CacheEntry | None:
        path = self._path_for(url)
        try:
            data = await anyio.to_thread.run_sync(self._read_json, path)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        entry = CacheEntry.from_dict(data)
        if self._is_expired(entry.cached_at):
            return None
        logger.info("pre_scrape_cache_hit", extra={"source": "cache"})
        return entry

    async def put(self, url: str, items: list[dict[str, Any]], truncated: bool) -> None:
        entry = CacheEntry(
            url=url,
            items=items,
            truncated=truncated,
            cached_at=datetime.now(timezone.utc).isoformat(),
        )
        path = self._path_for(url)
        await anyio.to_thread.run_sync(
            self._write_json, path, entry.to_dict()
        )

    async def get_seed(self, url: str) -> CacheEntry | None:
        if not self._seed_enabled or not self._seed:
            return None
        data = self._seed.get(seed_key(url))
        if data is None:
            return None
        logger.info("pre_scrape_seed_fallback", extra={"source": "seed"})
        return CacheEntry.from_dict(data)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)

    def _is_expired(self, cached_at: str) -> bool:
        if not cached_at:
            return True
        try:
            parsed = datetime.fromisoformat(cached_at)
        except ValueError:
            return True
        age = (datetime.now(timezone.utc) - parsed).total_seconds()
        return age > self._ttl_seconds


def load_seed_file(seed_path: str | Path) -> dict[str, dict[str, Any]]:
    path = Path(seed_path)
    if not path.exists():
        logger.warning("seed_file_missing", extra={"path": str(path)})
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
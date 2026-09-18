"""Environment configuration for the backend (ORB-NFR-005).

Variables are read from the process environment and, if present, from a local
`.env` file (never committed). See `Backend/.env.example` for the documented
defaults.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORBIT_",
        env_file=".env",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"
    scraper_timeout: float = 10.0
    scraper_max_body_size: int = 2 * 1024 * 1024
    scraper_cache_dir: str = ".cache/scraping"
    scraper_seed_file: str | None = None
    scraper_seed_enabled: bool = True
    scraper_cache_ttl: int = 3600

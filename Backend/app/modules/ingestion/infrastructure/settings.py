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

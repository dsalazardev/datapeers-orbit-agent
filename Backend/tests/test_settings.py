"""Settings defaults and environment overrides (ORB-NFR-005, design D3)."""

from __future__ import annotations

from app.core.settings import Settings


def test_defaults_match_the_documented_env_example():
    """`Backend/.env.example` documents these defaults; startup needs no env."""
    settings = Settings(_env_file=None)
    assert settings.app_env == "local"
    assert settings.log_level == "INFO"


def test_environment_variables_override_defaults(monkeypatch):
    monkeypatch.setenv("ORBIT_APP_ENV", "staging")
    monkeypatch.setenv("ORBIT_LOG_LEVEL", "DEBUG")
    settings = Settings(_env_file=None)
    assert settings.app_env == "staging"
    assert settings.log_level == "DEBUG"

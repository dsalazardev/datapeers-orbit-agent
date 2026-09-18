"""ORB-SCRAPE-000: zero client/prospect-specific hardcodes in the module."""

from __future__ import annotations

from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[1] / "app" / "modules" / "scraping"
FORBIDDEN_TERMS = ("jyp", "clientes-vis", "somos-jyp", "negocio-con-jyp")


def _source_files() -> list[Path]:
    return [path for path in MODULE_DIR.rglob("*.py") if "__pycache__" not in path.parts]


def test_module_has_no_client_specific_terms():
    for path in _source_files():
        content = path.read_text(encoding="utf-8").lower()
        for term in FORBIDDEN_TERMS:
            assert term not in content, f"forbidden term {term!r} found in {path}"
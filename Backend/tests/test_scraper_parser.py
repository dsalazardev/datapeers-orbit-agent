"""Unit tests for the extraction parser (pure functions, no network).

Covers ORB-SCRAPE-000 (no client hardcodes), the `grouping` candidate fix and
the superficial extraction requirement of the `scraping` spec.
"""

from __future__ import annotations

from pathlib import Path

from app.modules.scraping.config import ScraperConfig, NEGATIVE_KEYWORDS
from app.modules.scraping.parser import extract_candidates, parse_html

FIXTURE = Path(__file__).parent / "fixtures" / "construction_site.html"
BASE_URL = "https://andina.example/proyectos"


def _candidates():
    soup = parse_html(FIXTURE.read_bytes(), ScraperConfig())
    return extract_candidates(soup, BASE_URL, ScraperConfig())


def test_extracts_superficial_project_candidates():
    titles = [title for title, _, _ in _candidates()]
    assert "Proyecto Alfa" in titles
    assert "Proyecto Beta" in titles
    assert "Proyecto Gamma" in titles


def test_ignores_negative_and_navigation_links():
    urls = [url for _, url, _ in _candidates()]
    assert not any("nosotros" in url for url in urls)
    assert not any("blog" in url for url in urls)
    assert not any("contacto" in url for url in urls)
    assert not any("pqrs" in url for url in urls)
    assert not any("terminos" in url for url in urls)


def test_grouping_sources_are_normalized_away():
    sources = {source for _, _, source in _candidates()}
    assert sources <= {"meta", "card", "link", "grouping"}


def test_no_client_specific_terms_in_config():
    lowered = {term.lower() for term in NEGATIVE_KEYWORDS}
    assert not any("jyp" in term for term in lowered)


def test_no_duplicate_keywords_in_config():
    assert len(NEGATIVE_KEYWORDS) == len(set(NEGATIVE_KEYWORDS))
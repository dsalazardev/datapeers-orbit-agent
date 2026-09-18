"""Characterization tests for the navigation fallback and grouping return.

These lock the exact output of ``extract_candidates`` before the parser is
refactored to prune the tree in place instead of cloning it with
``copy.copy``. They are deliberately assertion-by-value (golden output) so the
refactor is only accepted when the observable behaviour is byte-for-byte the
same, including the intra-nav grouping duplicates caused by overlapping
navigation selectors.

Covers the ``scraping`` spec requirements for superficial extraction and
grouping detection (ORB-SCRAPE-000: no client hardcodes).
"""

from __future__ import annotations

from app.modules.scraping.config import ScraperConfig
from app.modules.scraping.parser import extract_candidates, parse_html

BASE_URL = "https://andina.example/proyectos"

NAV_FALLBACK_HTML = """
<html><head><title>Proyectos</title></head><body>
<header><nav class="navbar">
<a href="/proyecto-alfa">Proyecto Alfa</a>
<a href="/proyecto-beta">Proyecto Beta</a>
<a href="/contacto">Contacto</a>
<a href="/documento.pdf">Descargar</a>
<a href="https://otro.example/proyecto-x">Externo</a>
</nav></header>
<main><p>Sin enlaces.</p></main>
</body></html>
"""

GROUPING_FALLBACK_HTML = """
<html><body>
<nav>
<a href="/proyectos-en-bogota">Proyectos en Bogota</a>
<a href="/proyectos?page=2">Pagina 2</a>
<a href="/contacto">Contacto</a>
</nav>
</body></html>
"""

DEDUP_HTML = """
<html><head><title>Proyectos</title></head><body>
<main><article class="card"><a href="/proyecto-alfa">Proyecto Alfa</a></article></main>
<nav>
<a href="/proyecto-alfa">Proyecto Alfa</a>
<a href="/proyecto-beta">Proyecto Beta</a>
</nav>
</body></html>
"""

NAV_DUPLICATE_HTML = """
<html><body>
<nav class="menu"><a href="/proyectos-en-bogota">Proyectos en Bogota</a></nav>
</body></html>
"""


def _extract(html: str) -> list[tuple[str, str, str]]:
    soup = parse_html(html.encode("utf-8"), ScraperConfig())
    return list(extract_candidates(soup, BASE_URL, ScraperConfig()))


def test_nav_fallback_output_is_stable():
    assert _extract(NAV_FALLBACK_HTML) == [
        ("Proyecto Alfa", "https://andina.example/proyecto-alfa", "link"),
        ("Proyecto Beta", "https://andina.example/proyecto-beta", "link"),
    ]


def test_grouping_return_output_is_stable():
    assert _extract(GROUPING_FALLBACK_HTML) == [
        ("Proyectos en Bogota", "https://andina.example/proyectos-en-bogota", "grouping"),
        ("Pagina 2", "https://andina.example/proyectos?page=2", "grouping"),
    ]


def test_body_candidate_wins_over_duplicate_nav_link():
    assert _extract(DEDUP_HTML) == [
        ("Proyecto Alfa", "https://andina.example/proyecto-alfa", "card"),
        ("Proyecto Beta", "https://andina.example/proyecto-beta", "link"),
    ]


def test_intra_nav_grouping_duplicates_are_preserved():
    assert _extract(NAV_DUPLICATE_HTML) == [
        ("Proyectos en Bogota", "https://andina.example/proyectos-en-bogota", "grouping"),
        ("Proyectos en Bogota", "https://andina.example/proyectos-en-bogota", "grouping"),
    ]

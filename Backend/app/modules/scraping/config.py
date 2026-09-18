"""Externalized scraping rules and limits (no hardcoded client terms).

Domain-facing configuration for the pre-scraper. Client-specific or
prospect-specific terms are NOT allowed here (ORB-SCRAPE: zero hardcodes);
only generic, reusable rules live in this module. Values can be overridden
per environment through `Settings` (ORBIT_SCRAPER_*).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, Mapping

from app.core.settings import Settings

REQUEST_TIMEOUT: Final[float] = 10.0
MAX_BODY_SIZE: Final[int] = 2 * 1024 * 1024
SAFETY_FACTOR: Final[int] = 5

REQUEST_HEADERS: Final[Mapping[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_ASSET_FILE_RE: Final[re.Pattern[str]] = re.compile(
    r"\.(?:pdf|doc|docx|xls|xlsx|csv|ppt|pptx)"
    r"|\.(?:jpg|jpeg|png|gif|svg|webp|bmp|ico)"
    r"|\.(?:zip|rar|tar|gz|7z)"
    r"(?:[?#]|$)",
    re.IGNORECASE,
)

NAVIGATION_TAGS: Final[tuple[str, ...]] = ("nav", "header", "footer", "aside")

NAVIGATION_SELECTORS: Final[tuple[str, ...]] = (
    '[class*="menu" i]',
    '[id*="menu" i]',
    '[class*="navbar" i]',
    '[id*="navbar" i]',
    '[class*="sidebar" i]',
    '[id*="sidebar" i]',
    '[class*="topbar" i]',
    '[id*="topbar" i]',
    '[class*="breadcrumb" i]',
)

NEGATIVE_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "nosotros",
        "about",
        "aliados",
        "aliado",
        "partners",
        "constructora",
        "constructoras",
        "constructores",
        "contacto",
        "contactanos",
        "contactenos",
        "contact",
        "blog",
        "blogs",
        "equipo",
        "team",
        "faq",
        "faqs",
        "preguntas",
        "frecuentes",
        "login",
        "ingreso",
        "signin",
        "registro",
        "registrate",
        "registrar",
        "privacidad",
        "privacy",
        "terminos",
        "terms",
        "condiciones",
        "condiciones-de-uso",
        "legal",
        "aviso-legal",
        "noticias",
        "noticia",
        "news",
        "prensa",
        "galeria",
        "gallery",
        "testimonios",
        "trabaja",
        "empleo",
        "ofertas",
        "careers",
        "carreras",
        "campus",
        "somos",
        "quienes",
        "quienes-somos",
        "somos-una",
        "estrategia",
        "estrategias",
        "vision",
        "mision",
        "valores",
        "valores-corporativos",
        "cliente",
        "clientes",
        "pqrf",
        "pqr",
        "pqrs",
        "quejas",
        "reclamos",
        "felicitaciones",
        "sugerencias",
        "realizados",
        "realizado",
        "terminados",
        "terminado",
        "finalizados",
        "entregados",
        "video",
        "videos",
        "video-institucional",
        "video-institucionales",
        "institucional",
        "institucionales",
        "ver-video",
        "ver-nuestro-video",
        "negocio",
        "negocios",
        "tu-negocio",
        "empresa",
        "empresas",
        "imagen-institucional",
        "unete",
        "acerca",
        "acerca-de",
        "historia",
        "politicas",
        "politica",
        "politica-de-privacidad",
        "proteccion",
        "datos",
        "personales",
        "sagrilaft",
        "manual",
        "tratamiento",
        "documentos",
        "transparencia",
        "terminos-y-condiciones",
        "subsidio",
        "subsidios",
        "descarga",
        "descargar",
        "descargas",
        "download",
        "folleto",
        "folletos",
        "brochure",
        "catalogo",
        "catalogos",
        "invertir",
        "invierte",
        "inversion",
        "inversiones",
        "inversor",
        "emigrantes",
        "exterior",
        "comprar",
    }
)

INDEX_TERMS: Final[frozenset[str]] = frozenset(
    {
        "proyectos",
        "projectos",
        "desarrollos",
        "desarrollos-inmobiliarios",
        "proyectos-de-vivienda",
        "proyectos-de-vivienda-en",
        "proyectos-en",
        "desarrollos-urbano",
        "categoria",
        "categorias",
        "category",
        "categories",
        "indice",
        "index",
        "listado",
        "listados",
        "inicio",
        "home",
    }
)

REGIONAL_TERMS: Final[frozenset[str]] = frozenset(
    {
        "ciudad",
        "ciudades",
        "city",
        "cities",
        "region",
        "regiones",
        "regional",
        "resident",
        "residencia",
        "zona",
        "zonas",
        "departamento",
        "municipio",
        "provincia",
        "comunas",
    }
)

REGIONAL_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:proyectos?|projectos?|desarrollos?|apartamentos?)(?:-de-vivienda)?-en-"
)

WEAK_TITLES: Final[frozenset[str]] = frozenset(
    {
        "ver",
        "ver mas",
        "ver más",
        "ver video",
        "ver videos",
        "ver-catalogo",
        "ver-proyectos",
        "leer",
        "leer mas",
        "leer más",
        "mas",
        "más",
        "ver detalles",
        "detalles",
    }
)

PAGINATION_PARAMS: Final[frozenset[str]] = frozenset(
    {
        "page",
        "pagina",
        "paginas",
        "categoria",
        "categorias",
        "category",
        "categories",
        "tag",
        "tags",
        "filtro",
        "filter",
        "listado",
        "todos",
    }
)


@dataclass(frozen=True, slots=True)
class ScraperConfig:
    """Immutable view of the scraper rules consumed by the domain parser.

    The parser receives this object by parameter and never imports
    environment-specific or client-specific constants (ORB-SCRAPE-000).
    """

    request_timeout: float = REQUEST_TIMEOUT
    max_body_size: int = MAX_BODY_SIZE
    max_items: int = 10
    safety_factor: int = SAFETY_FACTOR
    request_headers: Mapping[str, str] = field(default_factory=lambda: REQUEST_HEADERS)
    negative_keywords: frozenset[str] = field(default_factory=lambda: NEGATIVE_KEYWORDS)
    index_terms: frozenset[str] = field(default_factory=lambda: INDEX_TERMS)
    regional_terms: frozenset[str] = field(default_factory=lambda: REGIONAL_TERMS)
    regional_prefix_re: re.Pattern[str] = field(default_factory=lambda: REGIONAL_PREFIX_RE)
    weak_titles: frozenset[str] = field(default_factory=lambda: WEAK_TITLES)
    pagination_params: frozenset[str] = field(default_factory=lambda: PAGINATION_PARAMS)
    navigation_tags: tuple[str, ...] = field(default_factory=lambda: NAVIGATION_TAGS)
    navigation_selectors: tuple[str, ...] = field(default_factory=lambda: NAVIGATION_SELECTORS)
    asset_file_re: re.Pattern[str] = field(default_factory=lambda: _ASSET_FILE_RE)

    @classmethod
    def from_settings(cls, settings: Settings) -> ScraperConfig:
        return cls(
            request_timeout=settings.scraper_timeout,
            max_body_size=settings.scraper_max_body_size,
        )
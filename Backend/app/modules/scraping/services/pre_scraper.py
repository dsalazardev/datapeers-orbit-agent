import re
from urllib.parse import parse_qsl, urljoin, urlparse
from typing import Literal

import httpx
from bs4 import BeautifulSoup

from app.modules.scraping.schemas import MAX_ITEMS, PreScrapeRequest, ProjectItem

REQUEST_TIMEOUT = 10.0
MAX_BODY_SIZE = 2 * 1024 * 1024

_ASSET_FILE_RE = re.compile(
    r"\.(?:pdf|doc|docx|xls|xlsx|csv|ppt|pptx)"
    r"|\.(?:jpg|jpeg|png|gif|svg|webp|bmp|ico)"
    r"|\.(?:zip|rar|tar|gz|7z)"
    r"(?:[?#]|$)",
    re.IGNORECASE,
)

REQUEST_HEADERS = {
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

Candidate = tuple[str, str, Literal["meta", "card", "link"]]

NAVIGATION_TAGS = ["nav", "header", "footer", "aside"]
NAVIGATION_SELECTORS = (
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

NEGATIVE_KEYWORDS = frozenset(
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
        "quienes-somos",
        "somos-una",
        "somos-jyp",
        "estrategia",
        "estrategias",
        "vision",
        "mision",
        "valores",
        "valores-corporativos",
        "zona-clientes",
        "zona-cliente",
        "zonas-clientes",
        "cliente",
        "clientes",
        "clientes-vis",
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
        "negocio-con-jyp",
        "tu-negocio",
        "tu-negocio-con-jyp",
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
        "subsidio",
        "subsidios",
        "descarga",
        "descargar",
        "descargas",
        "manual",
        "documentos",
    }
)

INDEX_TERMS = frozenset(
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

REGIONAL_TERMS = frozenset(
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

REGIONAL_PREFIX_RE = re.compile(
    r"(?:proyectos?|projectos?|desarrollos?|apartamentos?)(?:-de-vivienda)?-en-"
)

WEAK_TITLES = frozenset(
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

PAGINATION_PARAMS = frozenset(
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


class PreScrapeError(Exception):
    pass


class PreScraper:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def run(self, request: PreScrapeRequest) -> list[ProjectItem]:
        target = str(request.url)
        try:
            if self._client is not None:
                response = await self._client.get(
                    target,
                    headers=REQUEST_HEADERS,
                    timeout=REQUEST_TIMEOUT,
                    follow_redirects=True,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT, follow_redirects=True
                ) as client:
                    response = await client.get(target, headers=REQUEST_HEADERS)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PreScrapeError(str(exc)) from exc
        except ValueError as exc:
            raise PreScrapeError(str(exc)) from exc

        soup = BeautifulSoup(response.content[:MAX_BODY_SIZE], "html.parser")
        candidates = self._extract_cascade(
            soup, target, response.content[:MAX_BODY_SIZE]
        )
        items = [
            ProjectItem(id=index, title=title, url=url, source=source)
            for index, (title, url, source) in enumerate(candidates, start=1)
        ]
        return items[: request.max_items]

    def _extract_cascade(
        self, soup: BeautifulSoup, base_url: str, html: bytes
    ) -> list[Candidate]:
        self._prune_navigation(soup)
        candidates: list[Candidate] = []
        grouping: list[Candidate] = []
        seen_urls: set[str] = {base_url}
        self._extract_from_meta(soup, base_url, seen_urls, candidates, grouping)
        if len(candidates) < MAX_ITEMS:
            self._extract_from_cards(soup, base_url, seen_urls, candidates, grouping)
        if len(candidates) < MAX_ITEMS:
            self._extract_from_links(soup, base_url, seen_urls, candidates, grouping)
        if len(candidates) < MAX_ITEMS:
            self._extract_from_navigation(html, base_url, seen_urls, candidates, grouping)
        if not candidates:
            return grouping
        return candidates

    def _extract_from_meta(
        self,
        soup: BeautifulSoup,
        base_url: str,
        seen_urls: set[str],
        candidates: list[Candidate],
        grouping: list[Candidate],
    ) -> None:
        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            self._push_candidate(
                (title_tag.get_text(strip=True), base_url, "meta"),
                candidates,
                grouping,
                base_url,
            )
        og_url = soup.find("meta", {"property": "og:url"})
        og_title = soup.find("meta", {"property": "og:title"})
        if og_url and og_title and og_url.get("content") and og_title.get("content"):
            og_url_value = og_url["content"]
            if og_url_value not in seen_urls:
                seen_urls.add(og_url_value)
                self._push_candidate(
                    (og_title["content"], og_url_value, "meta"),
                    candidates,
                    grouping,
                    base_url,
                )

    def _extract_from_cards(
        self,
        soup: BeautifulSoup,
        base_url: str,
        seen_urls: set[str],
        candidates: list[Candidate],
        grouping: list[Candidate],
    ) -> None:
        for card in soup.select('[class*="card" i]'):
            if card.select_one('[class*="card" i]'):
                continue
            link = card.find("a", href=True)
            if not link:
                continue
            href = link.get("href", "").strip()
            if self._is_navigational_href(href):
                continue
            url = urljoin(base_url, href)
            title = self._link_title(link)
            if self._is_weak_title(title):
                title = self._slug_title(url)
            if not title:
                continue
            if not self._is_project_url(url) or url in seen_urls:
                continue
            if not self._is_same_host(url, base_url) or self._is_asset_file(url):
                continue
            seen_urls.add(url)
            self._push_candidate(
                (title, url, "card"), candidates, grouping, base_url
            )
            if len(candidates) >= MAX_ITEMS:
                break

    def _extract_from_links(
        self,
        soup: BeautifulSoup,
        base_url: str,
        seen_urls: set[str],
        candidates: list[Candidate],
        grouping: list[Candidate],
    ) -> None:
        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            if self._is_navigational_href(href):
                continue
            url = urljoin(base_url, href)
            title = self._link_title(link)
            if self._is_weak_title(title):
                title = self._slug_title(url)
            if not title:
                continue
            if not self._is_project_url(url) or url in seen_urls:
                continue
            if not self._is_same_host(url, base_url) or self._is_asset_file(url):
                continue
            seen_urls.add(url)
            self._push_candidate(
                (title, url, "link"), candidates, grouping, base_url
            )
            if len(candidates) >= MAX_ITEMS:
                break

    def _extract_from_navigation(
        self,
        html: bytes,
        base_url: str,
        seen_urls: set[str],
        candidates: list[Candidate],
        grouping: list[Candidate],
    ) -> None:
        soup = BeautifulSoup(html, "html.parser")
        navigation_nodes: list = []
        for tag in soup.find_all(NAVIGATION_TAGS):
            navigation_nodes.append(tag)
        for selector in NAVIGATION_SELECTORS:
            navigation_nodes.extend(soup.select(selector))
        for node in navigation_nodes:
            for link in node.find_all("a", href=True):
                href = link.get("href", "").strip()
                if self._is_navigational_href(href):
                    continue
                url = urljoin(base_url, href)
                title = self._link_title(link)
                if self._is_weak_title(title):
                    title = self._slug_title(url)
                if not title:
                    continue
                if not self._is_project_url(url) or url in seen_urls:
                    continue
                if self._is_grouping_url(url):
                    grouping.append((title, url, "grouping"))
                    continue
                if not self._is_same_host(url, base_url):
                    continue
                if self._is_asset_file(url):
                    continue
                if self._has_negative_keyword(title) or self._is_negative_url(url):
                    continue
                seen_urls.add(url)
                candidates.append((title, url, "link"))
                if len(candidates) >= MAX_ITEMS:
                    return

    @staticmethod
    def _link_title(link) -> str:
        title = link.get_text(" ", strip=True)
        return title if title else ""

    @staticmethod
    def _is_weak_title(title: str) -> bool:
        return title.casefold() in WEAK_TITLES

    @staticmethod
    def _slug_title(url: str) -> str:
        slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"\.[a-z0-9]+$", "", slug)
        slug = re.sub(r"[-_]", " ", slug).strip()
        if not slug:
            return ""
        return " ".join(word.capitalize() for word in slug.split())

    @staticmethod
    def _prune_navigation(soup: BeautifulSoup) -> None:
        for tag in soup.find_all(NAVIGATION_TAGS):
            tag.decompose()
        for selector in NAVIGATION_SELECTORS:
            for tag in soup.select(selector):
                tag.decompose()

    @staticmethod
    def _is_navigational_href(href: str) -> bool:
        if not href:
            return True
        if href.startswith("#") or href.startswith("javascript:"):
            return True
        return False

    @staticmethod
    def _is_project_url(url: str) -> bool:
        if not url.startswith(("http://", "https://")):
            return False
        if url.rstrip("/") == "":
            return False
        if url.endswith("#"):
            return False
        return True

    @staticmethod
    def _is_same_host(url: str, base_url: str) -> bool:
        return urlparse(url).netloc.lower() == urlparse(base_url).netloc.lower()

    @staticmethod
    def _is_asset_file(url: str) -> bool:
        return _ASSET_FILE_RE.search(url) is not None

    @staticmethod
    def _has_negative_keyword(text: str) -> bool:
        lowered = text.lower()
        tokens = set(re.findall(r"[a-z0-9]+", lowered))
        if tokens & NEGATIVE_KEYWORDS:
            return True
        return lowered.replace(" ", "-") in NEGATIVE_KEYWORDS

    @staticmethod
    def _is_negative_url(url: str) -> bool:
        parsed = urlparse(url)
        for segment in parsed.path.split("/"):
            if not segment:
                continue
            stem = re.sub(r"\.[a-z0-9]+$", "", segment.lower())
            for token in stem.replace("-", "_").split("_"):
                if token in NEGATIVE_KEYWORDS:
                    return True
        if parsed.query:
            for key, value in parse_qsl(parsed.query):
                if key.lower() in NEGATIVE_KEYWORDS:
                    return True
                if value.lower() in NEGATIVE_KEYWORDS:
                    return True
        return False

    @staticmethod
    def _is_grouping_url(url: str) -> bool:
        parsed = urlparse(url)
        if parsed.query:
            keys = {key.lower() for key, _ in parse_qsl(parsed.query)}
            if keys & PAGINATION_PARAMS:
                return True
        segments = [segment.lower() for segment in parsed.path.split("/") if segment]
        if not segments:
            return True
        last = re.sub(r"\.[a-z0-9]+$", "", segments[-1])
        if last in INDEX_TERMS:
            return True
        if REGIONAL_PREFIX_RE.search(parsed.path.lower()):
            return True
        if any(segment in REGIONAL_TERMS for segment in segments):
            return True
        return False

    def _push_candidate(
        self,
        candidate: Candidate,
        candidates: list[Candidate],
        grouping: list[Candidate],
        base_url: str | None = None,
    ) -> None:
        title, url, _ = candidate
        if self._is_asset_file(url):
            return
        if base_url is not None and not self._is_same_host(url, base_url):
            return
        if self._has_negative_keyword(title) or self._is_negative_url(url):
            return
        if self._is_grouping_url(url):
            grouping.append(candidate)
        else:
            candidates.append(candidate)
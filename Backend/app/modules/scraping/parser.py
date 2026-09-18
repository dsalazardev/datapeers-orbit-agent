"""Pure HTML parsing and candidate extraction for the pre-scraper.

This module contains NO I/O: it takes already-fetched HTML (bytes) and returns
candidate tuples. It receives all adjustable rules through a ``ScraperConfig``
parameter, so no client-specific or environment-specific constant lives in the
domain code (ORB-SCRAPE-000).

The parsing is intentionally CPU-bound (BeautifulSoup DOM traversal). Callers
MUST run these functions through `anyio.to_thread.run_sync` so the event loop
stays free (ORB-SCRAPE-001).
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup

from app.modules.scraping.config import ScraperConfig

CandidateSource = Literal["meta", "card", "link", "grouping"]
Candidate = tuple[str, str, CandidateSource]


def parse_html(html: bytes, config: ScraperConfig) -> BeautifulSoup:
    """Parse the fetched HTML exactly once per request."""
    return BeautifulSoup(html[: config.max_body_size], "html.parser")


def extract_candidates(
    soup: BeautifulSoup, base_url: str, config: ScraperConfig
) -> list[Candidate]:
    """Cascade extraction over a single parsed tree (meta -> cards -> links).

    The navigation fallback is read FIRST into its own buckets, then the tree is
    pruned in place and the main cascade runs over that SAME tree. Candidates
    from navigation are merged LAST so the precedence stays
    meta > cards > links > navigation; merging also reproduces the original
    cross-bucket deduplication. This keeps one parse per request and one DOM
    (no structural clone), see ORB-SCRAPE-001.
    """
    nav_candidates: list[Candidate] = []
    nav_grouping: list[Candidate] = []
    _extract_from_navigation(
        soup, base_url, config, {base_url}, nav_candidates, nav_grouping
    )

    candidates: list[Candidate] = []
    grouping: list[Candidate] = []
    seen_urls: set[str] = {base_url}

    _prune_navigation(soup, config)
    _extract_from_meta(soup, base_url, config, seen_urls, candidates, grouping)
    if len(candidates) < config.max_items:
        _extract_from_cards(soup, base_url, config, seen_urls, candidates, grouping)
    if len(candidates) < config.max_items:
        _extract_from_links(soup, base_url, config, seen_urls, candidates, grouping)

    if len(candidates) < config.max_items:
        _merge_link_candidates(nav_candidates, candidates, seen_urls, config.max_items)
    _merge_grouping_candidates(nav_grouping, grouping, seen_urls)

    if not candidates:
        return grouping
    return candidates


def _merge_link_candidates(
    nav_candidates: list[Candidate],
    candidates: list[Candidate],
    seen_urls: set[str],
    max_items: int,
) -> None:
    for candidate in nav_candidates:
        if candidate[1] in seen_urls:
            continue
        seen_urls.add(candidate[1])
        candidates.append(candidate)
        if len(candidates) >= max_items:
            return


def _merge_grouping_candidates(
    nav_grouping: list[Candidate],
    grouping: list[Candidate],
    seen_urls: set[str],
) -> None:
    for candidate in nav_grouping:
        if candidate[1] in seen_urls:
            continue
        grouping.append(candidate)


def _extract_from_meta(
    soup: BeautifulSoup,
    base_url: str,
    config: ScraperConfig,
    seen_urls: set[str],
    candidates: list[Candidate],
    grouping: list[Candidate],
) -> None:
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        _push_candidate(
            (title_tag.get_text(strip=True), base_url, "meta"),
            candidates,
            grouping,
            base_url,
            config,
        )
    og_url = soup.find("meta", {"property": "og:url"})
    og_title = soup.find("meta", {"property": "og:title"})
    if og_url and og_title and og_url.get("content") and og_title.get("content"):
        og_url_value = og_url["content"]
        if og_url_value not in seen_urls:
            seen_urls.add(og_url_value)
            _push_candidate(
                (og_title["content"], og_url_value, "meta"),
                candidates,
                grouping,
                base_url,
                config,
            )


def _extract_from_cards(
    soup: BeautifulSoup,
    base_url: str,
    config: ScraperConfig,
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
        if _is_navigational_href(href):
            continue
        url = urljoin(base_url, href)
        title = _link_title(link)
        if title and _is_weak_title(title, config):
            title = _slug_title(url)
        if not title:
            continue
        if not _is_project_url(url) or url in seen_urls:
            continue
        if not _is_same_host(url, base_url) or _is_asset_file(url, config):
            continue
        seen_urls.add(url)
        _push_candidate((title, url, "card"), candidates, grouping, base_url, config)
        if len(candidates) >= config.max_items:
            break


def _extract_from_links(
    soup: BeautifulSoup,
    base_url: str,
    config: ScraperConfig,
    seen_urls: set[str],
    candidates: list[Candidate],
    grouping: list[Candidate],
) -> None:
    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if _is_navigational_href(href):
            continue
        url = urljoin(base_url, href)
        title = _link_title(link)
        if title and _is_weak_title(title, config):
            title = _slug_title(url)
        if not title:
            continue
        if not _is_project_url(url) or url in seen_urls:
            continue
        if not _is_same_host(url, base_url) or _is_asset_file(url, config):
            continue
        seen_urls.add(url)
        _push_candidate((title, url, "link"), candidates, grouping, base_url, config)
        if len(candidates) >= config.max_items:
            break


def _extract_from_navigation(
    soup: BeautifulSoup,
    base_url: str,
    config: ScraperConfig,
    seen_urls: set[str],
    candidates: list[Candidate],
    grouping: list[Candidate],
) -> None:
    cap = config.max_items * config.safety_factor
    collected = 0
    for node in _navigation_nodes(soup, config):
        for link in node.find_all("a", href=True):
            href = link.get("href", "").strip()
            if _is_navigational_href(href):
                continue
            url = urljoin(base_url, href)
            title = _link_title(link)
            if title and _is_weak_title(title, config):
                title = _slug_title(url)
            if not title:
                continue
            if not _is_project_url(url) or url in seen_urls:
                continue
            if _is_grouping_url(url, config):
                grouping.append((title, url, "grouping"))
                collected += 1
                if collected >= cap:
                    return
                continue
            if not _is_same_host(url, base_url):
                continue
            if _is_asset_file(url, config):
                continue
            if _has_negative_keyword(title, config) or _is_negative_url(url, config):
                continue
            seen_urls.add(url)
            candidates.append((title, url, "link"))
            collected += 1
            if collected >= cap:
                return


def _navigation_nodes(soup: BeautifulSoup, config: ScraperConfig) -> list[object]:
    nodes: list[object] = []
    for tag in soup.find_all(list(config.navigation_tags)):
        nodes.append(tag)
    for selector in config.navigation_selectors:
        nodes.extend(soup.select(selector))
    return nodes


def _prune_navigation(soup: BeautifulSoup, config: ScraperConfig) -> None:
    for tag in soup.find_all(list(config.navigation_tags)):
        tag.decompose()
    for selector in config.navigation_selectors:
        for tag in soup.select(selector):
            tag.decompose()


def _link_title(link: object) -> str:
    return link.get_text(" ", strip=True)  # type: ignore[attr-defined]


def _is_weak_title(title: str, config: ScraperConfig) -> bool:
    return title.casefold() in config.weak_titles


def _slug_title(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.[a-z0-9]+$", "", slug)
    slug = re.sub(r"[-_]", " ", slug).strip()
    if not slug:
        return ""
    return " ".join(word.capitalize() for word in slug.split())


def _is_navigational_href(href: str) -> bool:
    if not href:
        return True
    return href.startswith("#") or href.startswith("javascript:")


def _is_project_url(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    if url.rstrip("/") == "" or url.endswith("#"):
        return False
    return True


def _is_same_host(url: str, base_url: str) -> bool:
    return urlparse(url).netloc.lower() == urlparse(base_url).netloc.lower()


def _is_asset_file(url: str, config: ScraperConfig) -> bool:
    return config.asset_file_re.search(url) is not None


def _has_negative_keyword(text: str, config: ScraperConfig) -> bool:
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", lowered))
    if tokens & config.negative_keywords:
        return True
    return lowered.replace(" ", "-") in config.negative_keywords


def _is_negative_url(url: str, config: ScraperConfig) -> bool:
    parsed = urlparse(url)
    for segment in parsed.path.split("/"):
        if not segment:
            continue
        stem = re.sub(r"\.[a-z0-9]+$", "", segment.lower())
        for token in stem.replace("-", "_").split("_"):
            if token in config.negative_keywords:
                return True
    if parsed.query:
        for key, value in parse_qsl(parsed.query):
            if key.lower() in config.negative_keywords or value.lower() in config.negative_keywords:
                return True
    return False


def _is_grouping_url(url: str, config: ScraperConfig) -> bool:
    parsed = urlparse(url)
    if parsed.query:
        keys = {key.lower() for key, _ in parse_qsl(parsed.query)}
        if keys & config.pagination_params:
            return True
    segments = [segment.lower() for segment in parsed.path.split("/") if segment]
    if not segments:
        return True
    last = re.sub(r"\.[a-z0-9]+$", "", segments[-1])
    if last in config.index_terms:
        return True
    if config.regional_prefix_re.search(parsed.path.lower()):
        return True
    if any(segment in config.regional_terms for segment in segments):
        return True
    return False


def _push_candidate(
    candidate: Candidate,
    candidates: list[Candidate],
    grouping: list[Candidate],
    base_url: str | None,
    config: ScraperConfig,
) -> None:
    title, url, source = candidate
    if _is_asset_file(url, config):
        return
    if base_url is not None and not _is_same_host(url, base_url):
        return
    if _has_negative_keyword(title, config) or _is_negative_url(url, config):
        return
    if _is_grouping_url(url, config):
        grouping.append(candidate)
    else:
        candidates.append(candidate)
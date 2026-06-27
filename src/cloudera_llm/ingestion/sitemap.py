from __future__ import annotations

from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from cloudera_llm.ingestion.browser import BrowserSession
from cloudera_llm.ingestion.metadata import url_fetch_priority

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def fetch_child_sitemaps(sitemap_index_url: str, session: BrowserSession) -> list[str]:
    return _fetch_sitemap_locs(sitemap_index_url, session)


def discover_urls(
    sitemap_index_url: str,
    session: BrowserSession,
    *,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    prioritize_support_matrix: bool = True,
    sitemap_only: bool = False,
) -> list[str]:
    include_patterns = include_patterns or []
    exclude_patterns = exclude_patterns or []

    if sitemap_only:
        sitemaps_to_load = [sitemap_index_url]
    else:
        child_sitemaps = fetch_child_sitemaps(sitemap_index_url, session)
        sitemaps_to_load = [
            loc
            for loc in child_sitemaps
            if _sitemap_is_relevant(loc, include_patterns, exclude_patterns)
        ]

        if include_patterns and not sitemaps_to_load:
            print("[sitemap] no child sitemap matched include filters; scanning all sitemaps for page matches")
            sitemaps_to_load = [
                loc for loc in child_sitemaps if _matches_patterns(loc, [], exclude_patterns)
            ]

    urls: list[str] = []
    seen: set[str] = set()
    for sitemap_url in sitemaps_to_load:
        if not sitemap_only:
            print(f"[sitemap] loading {sitemap_url}")
        page_urls = _fetch_sitemap_locs(sitemap_url, session)
        kept = 0
        for page_url in page_urls:
            if page_url in seen:
                continue
            if not _is_html_doc(page_url):
                continue
            if not _matches_patterns(page_url, include_patterns, exclude_patterns):
                continue
            seen.add(page_url)
            urls.append(page_url)
            kept += 1
        if not sitemap_only:
            print(f"[sitemap] kept {kept}/{len(page_urls)} URLs from {sitemap_url}")

    if prioritize_support_matrix:
        urls.sort(key=url_fetch_priority)

    return urls


def _sitemap_is_relevant(
    sitemap_url: str,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> bool:
    if exclude_patterns and any(pattern in sitemap_url for pattern in exclude_patterns):
        return False
    if not include_patterns:
        return True

    for pattern in include_patterns:
        if pattern in sitemap_url:
            return True
        product_root = _product_root(pattern)
        if product_root and product_root in sitemap_url:
            return True
    return False


def _product_root(pattern: str) -> str:
    parts = [part for part in pattern.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if parts else ""


def _fetch_sitemap_locs(sitemap_url: str, session: BrowserSession) -> list[str]:
    result = session.get(sitemap_url)
    root = ET.fromstring(result.text.encode("utf-8"))
    return [loc.text.strip() for loc in root.findall(".//sm:loc", SITEMAP_NS) if loc.text]


def _matches_patterns(
    url: str,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> bool:
    if exclude_patterns and any(pattern in url for pattern in exclude_patterns):
        return False
    if not include_patterns:
        return True
    return any(pattern in url for pattern in include_patterns)


def _is_html_doc(url: str) -> bool:
    path = urlparse(url).path.lower()
    if path.endswith((".html", ".htm")):
        return True
    if path.endswith("/") or path.endswith("index.html"):
        return True
    return "/topics/" in path or "/administration/" in path

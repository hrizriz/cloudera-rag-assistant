from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from cloudera_llm.config import AppConfig, get_config, raw_data_path
from cloudera_llm.ingestion.browser import BrowserSession
from cloudera_llm.ingestion.sitemap import discover_urls
from cloudera_llm.ingestion.metadata import parse_cloudera_url
from cloudera_llm.ingestion.state import CrawlState


@dataclass
class ScrapedPage:
    url: str
    title: str
    text: str
    source_type: str = "web"
    product: str = ""
    product_name: str = ""
    version: str = ""
    service: str = ""
    doc_type: str = ""
    is_support_matrix: bool = False


@dataclass
class CrawlStats:
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    total_target: int = 0


class ClouderaDocScraper:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or get_config()
        ingestion = self.config.ingestion
        self.session = BrowserSession(
            proxy=ingestion.proxy or None,
            rotate_user_agent=ingestion.rotate_user_agent,
            retry_attempts=ingestion.retry_attempts,
            retry_backoff_seconds=ingestion.retry_backoff_seconds,
            cooldown_on_429_seconds=ingestion.cooldown_on_429_seconds,
            delay_seconds=ingestion.delay_seconds,
            delay_jitter_seconds=ingestion.delay_jitter_seconds,
        )
        self.state = CrawlState()

    def crawl(self) -> list[ScrapedPage]:
        ingestion = self.config.ingestion
        if ingestion.resume:
            self.state.load_completed_from_disk()

        if ingestion.warmup_url:
            print(f"[warmup] {ingestion.warmup_url}")
            self.session.warmup(ingestion.warmup_url)

        if ingestion.mode in {"sitemap", "both"}:
            urls = discover_urls(
                ingestion.sitemap_index_url,
                self.session,
                include_patterns=ingestion.sitemap_include,
                exclude_patterns=ingestion.sitemap_exclude,
                prioritize_support_matrix=ingestion.prioritize_support_matrix,
            )
            matrix_count = sum(1 for url in urls if "matrix" in url.lower() or "compatibility" in url.lower())
            print(f"[sitemap] discovered {len(urls)} URLs ({matrix_count} support/compatibility pages prioritized)")
        else:
            urls = []

        if ingestion.mode in {"crawl", "both"}:
            urls.extend(self._discover_from_seeds())

        urls = _dedupe_preserve_order(urls)
        stats = CrawlStats(total_target=len(urls))
        pages: list[ScrapedPage] = []

        max_pages = ingestion.max_pages
        for index, url in enumerate(urls, start=1):
            if max_pages > 0 and stats.fetched >= max_pages:
                break

            if ingestion.resume and self.state.is_done(url):
                stats.skipped += 1
                continue

            print(f"[{index}/{len(urls)}] fetching {url}")
            page = self._fetch_page(url)
            if page is None:
                stats.failed += 1
                continue

            pages.append(page)
            self._save_raw_page(page)
            self.state.mark_done(url)
            stats.fetched += 1

            if stats.fetched % 25 == 0:
                self.state.save()

        self.state.save()
        print(
            f"[done] fetched={stats.fetched} skipped={stats.skipped} "
            f"failed={stats.failed} target={stats.total_target}"
        )
        return pages

    def _discover_from_seeds(self) -> list[str]:
        from collections import deque

        seeds = self.config.ingestion.seed_urls
        allowed = set(self.config.ingestion.allowed_domains)
        max_discover = self.config.ingestion.max_crawl_discover

        queue: deque[str] = deque()
        seen: set[str] = set()
        discovered: list[str] = []

        for seed in seeds:
            normalized = self._normalize_url(seed)
            if normalized:
                queue.append(normalized)
                seen.add(normalized)

        while queue and len(discovered) < max_discover:
            url = queue.popleft()
            discovered.append(url)
            try:
                result = self.session.get(url)
            except Exception as exc:
                print(f"[crawl-skip] {url}: {exc}")
                continue

            for link in self._extract_links(url, result.text):
                if link in seen:
                    continue
                domain = urlparse(link).netloc
                if domain not in allowed:
                    continue
                seen.add(link)
                queue.append(link)

        return discovered

    def _fetch_page(self, url: str) -> ScrapedPage | None:
        try:
            result = self.session.get(url)
        except Exception as exc:
            reason = str(exc)
            print(f"[fail] {url}: {reason}")
            self.state.mark_failed(url, reason)
            return None

        soup = BeautifulSoup(result.text, "lxml")
        title = _extract_title(soup)
        text = _extract_main_text(soup)
        if len(text) < 100:
            reason = "content too short"
            print(f"[skip] {url}: {reason}")
            self.state.mark_failed(url, reason)
            return None

        meta = parse_cloudera_url(url)
        return ScrapedPage(
            url=url,
            title=title,
            text=text,
            source_type="web",
            product=meta.product,
            product_name=meta.product_name,
            version=meta.version,
            service=meta.service,
            doc_type=meta.doc_type,
            is_support_matrix=meta.is_support_matrix,
        )

    def _extract_links(self, base_url: str, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or href.startswith("#") or href.startswith("mailto:"):
                continue
            absolute = urljoin(base_url, href)
            normalized = self._normalize_url(absolute)
            if normalized:
                links.append(normalized)
        return links

    def _normalize_url(self, url: str) -> str | None:
        cleaned, _ = urldefrag(url)
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"}:
            return None
        if not parsed.netloc:
            return None
        return cleaned

    def _save_raw_page(self, page: ScrapedPage) -> None:
        slug = _slugify(page.url)
        digest = hashlib.sha1(page.url.encode("utf-8")).hexdigest()[:10]
        payload = {
            "url": page.url,
            "title": page.title,
            "text": page.text,
            "source_type": page.source_type,
            "product": page.product,
            "product_name": page.product_name,
            "version": page.version,
            "service": page.service,
            "doc_type": page.doc_type,
            "is_support_matrix": page.is_support_matrix,
        }
        target = raw_data_path() / f"{slug}_{digest}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def close(self) -> None:
        self.state.save()
        self.session.close()


def _extract_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    heading = soup.find(["h1", "h2"])
    if heading:
        return heading.get_text(" ", strip=True)
    return "Untitled"


def _extract_main_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.find("div", class_="content")
    root = main if main else soup.body
    if root is None:
        return ""

    lines: list[str] = []
    for element in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "code", "td"]):
        text = element.get_text(" ", strip=True)
        if text:
            lines.append(text)

    if not lines:
        return root.get_text("\n", strip=True)

    return "\n".join(lines)


def _slugify(url: str) -> str:
    slug = urlparse(url).path.strip("/").replace("/", "_") or "index"
    return slug[:100]


def _dedupe_preserve_order(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique

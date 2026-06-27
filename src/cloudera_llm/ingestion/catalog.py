from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cloudera_llm.config import ROOT_DIR, get_config
from cloudera_llm.ingestion.browser import BrowserSession
from cloudera_llm.ingestion.metadata import (
    PRODUCT_NAMES,
    is_support_matrix_url,
    parse_cloudera_url,
    parse_sitemap_product_version,
)
from cloudera_llm.ingestion.sitemap import discover_urls, fetch_child_sitemaps


@dataclass
class ProductCatalogEntry:
    product: str
    product_name: str
    version: str
    page_count: int = 0
    services: list[str] = field(default_factory=list)
    support_matrix_urls: list[str] = field(default_factory=list)


def build_catalog(*, save_path: Path | None = None) -> dict:
    config = get_config()
    session = BrowserSession(
        proxy=config.ingestion.proxy or None,
        rotate_user_agent=config.ingestion.rotate_user_agent,
        retry_attempts=config.ingestion.retry_attempts,
        delay_seconds=0.5,
        delay_jitter_seconds=0.2,
    )

    try:
        if config.ingestion.warmup_url:
            session.warmup(config.ingestion.warmup_url)

        child_sitemaps = fetch_child_sitemaps(config.ingestion.sitemap_index_url, session)
        products: list[ProductCatalogEntry] = []
        all_services: set[str] = set()
        all_versions: set[str] = set()
        matrix_urls: list[str] = []

        for sitemap_url in child_sitemaps:
            product, version, product_name = parse_sitemap_product_version(sitemap_url)
            print(f"[catalog] scanning {product_name} ({version})")

            page_urls = discover_urls(
                sitemap_url,
                session,
                sitemap_only=True,
            )
            services: set[str] = set()
            product_matrix: list[str] = []

            for page_url in page_urls:
                meta = parse_cloudera_url(page_url)
                if meta.service:
                    services.add(meta.service)
                    all_services.add(meta.service)
                if meta.version and meta.version not in {"topics", "administration"}:
                    all_versions.add(f"{meta.product}/{meta.version}")
                if is_support_matrix_url(page_url):
                    product_matrix.append(page_url)
                    matrix_urls.append(page_url)

            products.append(
                ProductCatalogEntry(
                    product=product,
                    product_name=product_name,
                    version=version,
                    page_count=len(page_urls),
                    services=sorted(services),
                    support_matrix_urls=sorted(product_matrix),
                )
            )

        catalog = {
            "product_count": len(products),
            "total_pages": sum(item.page_count for item in products),
            "support_matrix_count": len(matrix_urls),
            "known_products": PRODUCT_NAMES,
            "detected_services": sorted(all_services),
            "detected_versions": sorted(all_versions),
            "products": [asdict(item) for item in products],
            "support_matrix_urls": sorted(set(matrix_urls)),
        }

        target = save_path or (ROOT_DIR / "data" / "catalog.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"[catalog] saved {target} "
            f"products={catalog['product_count']} pages={catalog['total_pages']} "
            f"services={len(catalog['detected_services'])} "
            f"matrix={catalog['support_matrix_count']}"
        )
        return catalog
    finally:
        session.close()

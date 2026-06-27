from __future__ import annotations

import argparse

from cloudera_llm.ingestion.catalog import build_catalog
from cloudera_llm.rag.pipeline import RAGPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Cloudera knowledge into the vector store")
    parser.add_argument(
        "--source",
        choices=["web", "local", "all"],
        default="all",
        help="web=docs.cloudera.com, local=SOP/MOP files in data/, all=both",
    )
    parser.add_argument("--reset", action="store_true", help="Clear existing vectors before ingest")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Override max_pages from config.yaml (0 = unlimited)",
    )
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="Build product/service/version catalog from Cloudera sitemaps (saved to data/catalog.json)",
    )
    args = parser.parse_args()

    if args.catalog:
        build_catalog()
        if args.source == "all" and args.max_pages is None and not args.reset:
            return

    pipeline = RAGPipeline()
    if args.max_pages is not None:
        pipeline.config.ingestion.max_pages = args.max_pages

    if args.source == "web":
        print("Scraping Cloudera docs via sitemap (support matrix prioritized, resumable)...")
        stats = pipeline.ingest_from_web(reset=args.reset)
    elif args.source == "local":
        print("Loading local SOP/MOP files from data/...")
        stats = pipeline.ingest_from_local(reset=args.reset)
    else:
        print("Ingesting local files first, then web docs...")
        stats = pipeline.ingest_all(reset=args.reset)

    if "local_pages" in stats:
        print(
            f"Done. local_pages={stats['local_pages']} web_pages={stats['web_pages']} "
            f"chunks={stats['chunks']} total_vectors={stats['total_vectors']}"
        )
    else:
        print(
            f"Done. pages={stats['pages']} chunks={stats['chunks']} "
            f"total_vectors={stats['total_vectors']}"
        )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse

from cloudera_llm.ingestion.catalog import build_catalog


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Cloudera product/service/version catalog from official sitemaps"
    )
    parser.parse_args()
    catalog = build_catalog()
    print(f"Products: {catalog['product_count']}")
    print(f"Total pages: {catalog['total_pages']}")
    print(f"Services detected: {len(catalog['detected_services'])}")
    print(f"Support matrix pages: {catalog['support_matrix_count']}")
    print("Saved to data/catalog.json")


if __name__ == "__main__":
    main()

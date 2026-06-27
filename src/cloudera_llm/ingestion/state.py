from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cloudera_llm.config import raw_data_path


class CrawlState:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or raw_data_path() / "crawl_state.json"
        self.completed_urls: set[str] = set()
        self.failed_urls: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.completed_urls = set(payload.get("completed_urls", []))
        self.failed_urls = dict(payload.get("failed_urls", {}))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "completed_urls": sorted(self.completed_urls),
            "failed_urls": self.failed_urls,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_done(self, url: str) -> bool:
        return url in self.completed_urls

    def mark_done(self, url: str) -> None:
        self.completed_urls.add(url)
        self.failed_urls.pop(url, None)

    def mark_failed(self, url: str, reason: str) -> None:
        self.failed_urls[url] = reason

    def load_completed_from_disk(self) -> None:
        for file_path in raw_data_path().glob("*.json"):
            if file_path.name == "crawl_state.json":
                continue
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            url = payload.get("url")
            if url:
                self.completed_urls.add(url)

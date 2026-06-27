from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import httpx

DEFAULT_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
        "Gecko/20100101 Firefox/133.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
]


@dataclass
class FetchResult:
    url: str
    status_code: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)


class BrowserSession:
    """HTTP client tuned to reduce bot-detection triggers."""

    RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        timeout: float = 45.0,
        proxy: str | None = None,
        rotate_user_agent: bool = True,
        retry_attempts: int = 5,
        retry_backoff_seconds: float = 5.0,
        cooldown_on_429_seconds: float = 60.0,
        delay_seconds: float = 2.0,
        delay_jitter_seconds: float = 1.5,
    ) -> None:
        self.rotate_user_agent = rotate_user_agent
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.cooldown_on_429_seconds = cooldown_on_429_seconds
        self.delay_seconds = delay_seconds
        self.delay_jitter_seconds = delay_jitter_seconds
        self._last_url: str | None = None
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            proxy=proxy,
            headers=self._base_headers(),
        )

    def _base_headers(self) -> dict[str, str]:
        return self._build_headers()

    def _build_headers(self, referer: str | None = None) -> dict[str, str]:
        user_agent = random.choice(DEFAULT_USER_AGENTS) if self.rotate_user_agent else DEFAULT_USER_AGENTS[0]
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "DNT": "1",
        }
        if referer:
            headers["Referer"] = referer
            headers["Sec-Fetch-Site"] = "same-origin"
        else:
            headers["Sec-Fetch-Site"] = "none"
        return headers

    def warmup(self, url: str) -> None:
        self.get(url)

    def get(self, url: str) -> FetchResult:
        last_error: Exception | None = None
        referer = self._last_url

        for attempt in range(1, self.retry_attempts + 1):
            headers = self._build_headers(referer=referer)
            try:
                response = self.client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
                self._backoff(attempt, reason=str(exc))
                continue

            if response.status_code in self.RETRYABLE_STATUS:
                if response.status_code == 429:
                    time.sleep(self.cooldown_on_429_seconds)
                else:
                    self._backoff(attempt, reason=f"HTTP {response.status_code}")
                continue

            response.raise_for_status()
            self._last_url = str(response.url)
            self._human_delay()
            return FetchResult(
                url=str(response.url),
                status_code=response.status_code,
                text=response.text,
                headers=dict(response.headers),
            )

        if last_error is not None:
            raise last_error
        raise httpx.HTTPError(f"Failed to fetch {url} after {self.retry_attempts} attempts")

    def _backoff(self, attempt: int, *, reason: str) -> None:
        wait = self.retry_backoff_seconds * attempt + random.uniform(0, 1.5)
        print(f"[retry] attempt={attempt} wait={wait:.1f}s reason={reason}")
        time.sleep(wait)

    def _human_delay(self) -> None:
        if self.delay_seconds <= 0:
            return
        jitter = random.uniform(0, self.delay_jitter_seconds)
        time.sleep(self.delay_seconds + jitter)

    def close(self) -> None:
        self.client.close()

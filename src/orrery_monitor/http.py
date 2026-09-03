from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

DEFAULT_USER_AGENT = "OrrerySourceMonitor/0.1 (+https://ashwinprasadrao.github.io/source-monitor/)"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class HttpClient:
    """Synchronous, cached, bounded-retry HTTP client for one monitor run."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._cache: dict[str, httpx.Response] = {}
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "*/*"},
            transport=transport,
        )

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        method = method.upper()
        cache_key = self._cache_key(method, url, kwargs)
        if cache_key in self._cache:
            return self._cache[cache_key]

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            response: httpx.Response | None = None
            try:
                response = self._client.request(method, url, **kwargs)
                response.read()
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    response.raise_for_status()
                    self._cache[cache_key] = response
                    return response
                last_error = httpx.HTTPStatusError(
                    f"retryable status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc

            if attempt < self.max_attempts:
                delay = self._retry_delay(response, attempt)
                self._sleep(delay)

        assert last_error is not None
        raise last_error

    @staticmethod
    def _cache_key(method: str, url: str, kwargs: dict[str, Any]) -> str:
        relevant = {
            key: kwargs[key]
            for key in ("params", "json", "data", "content", "headers")
            if key in kwargs
        }
        return f"{method} {url} {json.dumps(relevant, sort_keys=True, default=str)}"

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None and "Retry-After" in response.headers:
            retry_after = response.headers["Retry-After"].strip()
            if retry_after.isdigit():
                return min(float(retry_after), 60.0)
            try:
                target = parsedate_to_datetime(retry_after)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=UTC)
                return min(max((target - datetime.now(UTC)).total_seconds(), 0.0), 60.0)
            except (TypeError, ValueError, OverflowError):
                pass
        return self.backoff_seconds * (2 ** (attempt - 1))

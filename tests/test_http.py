import httpx
import pytest

from orrery_monitor.http import HttpClient


def test_http_client_retries_retryable_status_and_caches_success() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, headers={"Retry-After": "2"}, request=request)
        return httpx.Response(200, text="ok", request=request)

    with HttpClient(
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    ) as client:
        first = client.get("https://example.gov/data", params={"page": 1})
        second = client.get("https://example.gov/data", params={"page": 1})

    assert first.text == second.text == "ok"
    assert calls == 2
    assert sleeps == [2.0]


def test_http_client_stops_after_bounded_attempts() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    with (
        HttpClient(
            max_attempts=3,
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
        ) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.get("https://example.gov/unavailable")

    assert calls == 3

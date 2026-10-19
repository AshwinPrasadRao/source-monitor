import ssl

import certifi
import httpx
import pytest
import truststore

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


@pytest.mark.parametrize(
    "error_type", [httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectTimeout]
)
def test_interrupted_response_is_retried_and_only_success_is_cached(error_type) -> None:
    calls = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise error_type("Server disconnected without sending a response", request=request)
        return httpx.Response(200, text="recovered", request=request)

    with HttpClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        assert client.get("https://example.gov/data").text == "recovered"
        assert client.get("https://example.gov/data").text == "recovered"

    assert calls == 3
    assert sleeps == [1.0, 2.0]


def test_persistent_disconnect_stops_after_bounded_attempts() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.RemoteProtocolError("disconnected", request=request)

    with (
        HttpClient(transport=httpx.MockTransport(handler), sleep=lambda _: None) as client,
        pytest.raises(httpx.RemoteProtocolError),
    ):
        client.get("https://example.gov/data")

    assert calls == 3


def test_certificate_failure_is_not_retried_or_cached() -> None:
    calls = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("certificate verify failed", request=request) from (
            ssl.SSLCertVerificationError("untrusted certificate")
        )

    with HttpClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        for _ in range(2):
            with pytest.raises(httpx.ConnectError):
                client.get("https://example.gov/data")

    assert calls == 2
    assert sleeps == []


def test_native_tls_context_requires_certificate_and_hostname_verification(monkeypatch) -> None:
    # Inspect what is passed to the real transport, before replacing network I/O.
    contexts = []
    original_client = httpx.Client

    def capture_client(**kwargs):
        contexts.append(kwargs["verify"])
        return original_client(**kwargs)

    monkeypatch.setattr(httpx, "Client", capture_client)
    with HttpClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))):
        pass

    assert len(contexts) == 1
    assert isinstance(contexts[0], truststore.SSLContext)
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert contexts[0].check_hostname is True


def test_transport_does_not_depend_on_certifi_bundle(monkeypatch) -> None:
    def unavailable_bundle():
        raise AssertionError("monitor transport should use native CA policy")

    monkeypatch.setattr(certifi, "where", unavailable_bundle)
    # Construct the production transport without making a network request.
    with HttpClient():
        pass

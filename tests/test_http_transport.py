import asyncio
import ssl

import httpx
import pytest

from app.core.http import create_http_client, request_with_retries


def test_client_uses_bounded_timeout_and_safe_user_agent() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["User-Agent"] == "ai-powered-monitoring-dashboard/0.1"
            assert "Authorization" not in request.headers
            return httpx.Response(200, json={"ok": True})

        async with create_http_client(
            timeout_seconds=10,
            transport=httpx.MockTransport(handler),
        ) as client:
            assert client.timeout.connect == 10
            assert client.timeout.read == 10
            assert client.timeout.write == 10
            assert client.timeout.pool == 10
            response = await client.get("https://source.internal/health")

        assert response.status_code == 200

    asyncio.run(run())


def test_client_uses_conservative_connection_limits(monkeypatch) -> None:
    observed: dict[str, int] = {}
    real_limits = httpx.Limits

    def capture_limits(**kwargs):
        observed.update(kwargs)
        return real_limits(**kwargs)

    monkeypatch.setattr(httpx, "Limits", capture_limits)

    async def run() -> None:
        async with create_http_client(
            timeout_seconds=10,
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        ):
            pass

    asyncio.run(run())
    assert observed == {
        "max_connections": 20,
        "max_keepalive_connections": 10,
    }


def test_retry_is_disabled_by_default(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(503)

        async def fail_if_sleeping(delay: float) -> None:
            pytest.fail(f"unexpected retry sleep: {delay}")

        monkeypatch.setattr(asyncio, "sleep", fail_if_sleeping)

        async with create_http_client(
            timeout_seconds=10,
            transport=httpx.MockTransport(handler),
        ) as client:
            response = await request_with_retries(client, "GET", "https://source.internal")

        assert response.status_code == 503
        assert attempts == 1

    asyncio.run(run())


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_retry_safe_transient_statuses_use_two_bounded_retries(monkeypatch, status: int) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return httpx.Response(status)
            return httpx.Response(200)

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        async with create_http_client(
            timeout_seconds=10,
            transport=httpx.MockTransport(handler),
        ) as client:
            response = await request_with_retries(
                client,
                "POST",
                "https://source.internal/api_jsonrpc.php",
                retry_safe=True,
                json={"method": "host.get"},
            )

        assert response.status_code == 200
        assert attempts == 3
        assert delays == [0.25, 0.5]

    asyncio.run(run())


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_non_transient_4xx_is_not_retried(monkeypatch, status: int) -> None:
    async def run() -> None:
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(status)

        async def fail_if_sleeping(delay: float) -> None:
            pytest.fail(f"unexpected retry sleep: {delay}")

        monkeypatch.setattr(asyncio, "sleep", fail_if_sleeping)

        async with create_http_client(
            timeout_seconds=10,
            transport=httpx.MockTransport(handler),
        ) as client:
            response = await request_with_retries(
                client,
                "GET",
                "https://source.internal",
                retry_safe=True,
            )

        assert response.status_code == status
        assert attempts == 1

    asyncio.run(run())


@pytest.mark.parametrize("exception_type", [httpx.ConnectError, httpx.ConnectTimeout])
def test_retry_safe_connect_failure_is_bounded(monkeypatch, exception_type) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise exception_type("connection failed", request=request)
            return httpx.Response(200)

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        async with create_http_client(
            timeout_seconds=10,
            transport=httpx.MockTransport(handler),
        ) as client:
            response = await request_with_retries(
                client,
                "GET",
                "https://source.internal",
                retry_safe=True,
            )

        assert response.status_code == 200
        assert attempts == 3
        assert delays == [0.25, 0.5]

    asyncio.run(run())


def test_read_timeout_is_not_retried(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ReadTimeout("read timed out", request=request)

        async def fail_if_sleeping(delay: float) -> None:
            pytest.fail(f"unexpected retry sleep: {delay}")

        monkeypatch.setattr(asyncio, "sleep", fail_if_sleeping)

        async with create_http_client(
            timeout_seconds=10,
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(httpx.ReadTimeout):
                await request_with_retries(
                    client,
                    "GET",
                    "https://source.internal",
                    retry_safe=True,
                )

        assert attempts == 1

    asyncio.run(run())


def test_ca_bundle_is_used_for_tls_context(monkeypatch) -> None:
    calls: list[str | None] = []
    real_create_default_context = ssl.create_default_context

    def fake_create_default_context(*, cafile=None, **kwargs):
        calls.append(cafile)
        return real_create_default_context()

    monkeypatch.setattr(ssl, "create_default_context", fake_create_default_context)

    async def run() -> None:
        async with create_http_client(
            timeout_seconds=10,
            ca_bundle="/tmp/internal-ca.pem",
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        ):
            pass

    asyncio.run(run())
    assert calls == ["/tmp/internal-ca.pem"]


def test_final_retryable_response_is_returned_after_three_attempts(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(503)

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        async with create_http_client(
            timeout_seconds=10,
            transport=httpx.MockTransport(handler),
        ) as client:
            response = await request_with_retries(
                client,
                "GET",
                "https://source.internal",
                retry_safe=True,
            )

        assert response.status_code == 503
        assert attempts == 3
        assert delays == [0.25, 0.5]

    asyncio.run(run())

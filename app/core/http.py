import asyncio
import ssl
from pathlib import Path

import httpx


HTTP_USER_AGENT = "ai-powered-monitoring-dashboard/0.1"
HTTP_MAX_CONNECTIONS = 20
HTTP_MAX_KEEPALIVE_CONNECTIONS = 10
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
RETRY_DELAYS = (0.25, 0.5)


def _build_verify(
    verify_tls: bool,
    ca_bundle: str | Path | None,
) -> bool | ssl.SSLContext:
    if not verify_tls:
        return False
    if ca_bundle is not None:
        return ssl.create_default_context(cafile=str(ca_bundle))
    return True


def create_http_client(
    *,
    timeout_seconds: float,
    verify_tls: bool = True,
    ca_bundle: str | Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        verify=_build_verify(verify_tls, ca_bundle),
        limits=httpx.Limits(
            max_connections=HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=HTTP_MAX_KEEPALIVE_CONNECTIONS,
        ),
        headers={"User-Agent": HTTP_USER_AGENT},
        transport=transport,
    )


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retry_safe: bool = False,
    **kwargs,
) -> httpx.Response:
    max_attempts = 3 if retry_safe else 1

    for attempt in range(max_attempts):
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt + 1 >= max_attempts:
                raise
            await asyncio.sleep(RETRY_DELAYS[attempt])
            continue

        should_retry = retry_safe and response.status_code in RETRYABLE_STATUS_CODES
        if not should_retry or attempt + 1 >= max_attempts:
            return response

        await asyncio.sleep(RETRY_DELAYS[attempt])

    raise RuntimeError("retry loop exited without response")

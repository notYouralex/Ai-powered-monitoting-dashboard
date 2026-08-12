import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import IntegrationError
from app.integrations.freshservice.client import FreshserviceClient


UPDATED_SINCE = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)


def make_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "app_secret_key": "t" * 48,
        "database_url": "sqlite:///test.db",
        "freshservice_base_url": "https://company.freshservice.com",
        "freshservice_api_key": "fake-freshservice-api-key",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def ticket_payload(ticket_id: int = 101, **overrides) -> dict:
    payload = {
        "id": ticket_id,
        "subject": "Laptop cannot connect to VPN",
        "status": 2,
        "priority": 3,
        "type": "Incident",
        "category": "Network",
        "sub_category": "VPN",
        "item_category": None,
        "requester_id": 1001,
        "requested_for_id": 1002,
        "responder_id": 2001,
        "group_id": 3001,
        "department_id": 4001,
        "workspace_id": 2,
        "source": 2,
        "due_by": "2026-08-11T10:00:00Z",
        "fr_due_by": "2026-08-10T10:00:00Z",
        "is_escalated": False,
        "fr_escalated": False,
        "created_at": "2026-08-09T08:00:00Z",
        "updated_at": "2026-08-10T08:30:00Z",
        "stats": {
            "resolved_at": None,
            "closed_at": None,
            "first_responded_at": "2026-08-09T08:10:00Z",
        },
    }
    payload.update(overrides)
    return payload


def test_from_settings_rejects_unconfigured_freshservice() -> None:
    settings = make_settings(freshservice_base_url=None, freshservice_api_key=None)

    with pytest.raises(IntegrationError) as exc_info:
        FreshserviceClient.from_settings(settings)

    assert exc_info.value.source == "freshservice"
    assert exc_info.value.code == "SOURCE_NOT_CONFIGURED"
    assert exc_info.value.retryable is False


def test_list_tickets_uses_api_key_basic_auth_and_normalizes_ticket() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                headers={"X-RateLimit-Remaining": "99"},
                json={"tickets": [ticket_payload()]},
            )

        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        tickets = await client.list_tickets(updated_since=UPDATED_SINCE)

        assert len(requests) == 1
        request = requests[0]
        assert request.method == "GET"
        assert request.url.path == "/api/v2/tickets"
        assert request.headers["Authorization"].startswith("Basic ")
        assert request.headers["Accept"] == "application/json"
        assert request.url.params["page"] == "1"
        assert request.url.params["per_page"] == "100"
        assert request.url.params["include"] == "stats"
        assert request.url.params["updated_since"] == "2026-08-01T00:00:00Z"

        assert len(tickets) == 1
        ticket = tickets[0]
        assert ticket.ticket_id == 101
        assert ticket.subject == "Laptop cannot connect to VPN"
        assert ticket.status_code == 2
        assert ticket.status == "open"
        assert ticket.priority_code == 3
        assert ticket.priority == "high"
        assert ticket.ticket_type == "Incident"
        assert ticket.category == "Network"
        assert ticket.sub_category == "VPN"
        assert ticket.requester_id == 1001
        assert ticket.responder_id == 2001
        assert ticket.is_escalated is False
        assert ticket.first_responded_at is not None
        assert ticket.created_at.tzinfo is not None
        assert ticket.updated_at.tzinfo is not None

    asyncio.run(run())


@pytest.mark.parametrize(
    "base_url",
    [
        "http://company.freshservice.com",
        "https://support.example.com",
    ],
)
def test_from_settings_rejects_non_freshservice_https_base_url(base_url: str) -> None:
    with pytest.raises(IntegrationError) as exc_info:
        FreshserviceClient.from_settings(make_settings(freshservice_base_url=base_url))

    assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
    assert exc_info.value.retryable is False


def test_list_tickets_pages_using_link_header_without_following_header_url() -> None:
    async def run() -> None:
        pages: list[int] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params["page"])
            pages.append(page)
            if page == 1:
                return httpx.Response(
                    200,
                    headers={
                        "Link": '<https://attacker.invalid/api/v2/tickets?page=2>; rel="next"'
                    },
                    json={"tickets": [ticket_payload(101)]},
                )
            return httpx.Response(200, json={"tickets": [ticket_payload(102)]})

        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        tickets = await client.list_tickets()

        assert pages == [1, 2]
        assert [ticket.ticket_id for ticket in tickets] == [101, 102]

    asyncio.run(run())


def test_unknown_status_and_priority_are_preserved_as_codes() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"tickets": [ticket_payload(status=99, priority=88)]},
            )

        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        tickets = await client.list_tickets()

        assert tickets[0].status_code == 99
        assert tickets[0].status == "unknown"
        assert tickets[0].priority_code == 88
        assert tickets[0].priority == "unknown"

    asyncio.run(run())


def test_api_key_auth_failure_maps_without_leaking_key() -> None:
    async def run() -> None:
        api_key = "fake-key-that-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"description": api_key})

        client = FreshserviceClient.from_settings(
            make_settings(freshservice_api_key=api_key),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_tickets()

        assert exc_info.value.code == "SOURCE_AUTH_FAILED"
        assert exc_info.value.retryable is False
        assert api_key not in str(exc_info.value)
        assert api_key not in repr(exc_info.value)

    asyncio.run(run())


def test_rate_limit_waits_for_retry_after_and_resumes_same_page(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "2"},
                    json={"error": "limited"},
                )
            return httpx.Response(200, json={"tickets": [ticket_payload()]})

        monkeypatch.setattr("app.integrations.freshservice.client.asyncio.sleep", fake_sleep)
        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        tickets = await client.list_tickets()

        assert attempts == 2
        assert delays == [2]
        assert [ticket.ticket_id for ticket in tickets] == [101]

    asyncio.run(run())


def test_rate_limit_retry_is_bounded(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(
                429,
                headers={"Retry-After": "2"},
                json={"error": "limited"},
            )

        monkeypatch.setattr("app.integrations.freshservice.client.asyncio.sleep", fake_sleep)
        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_tickets()

        assert attempts == 4
        assert delays == [2, 2, 2]
        assert exc_info.value.code == "SOURCE_RATE_LIMITED"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_rate_limit_rejects_unsafe_retry_after_without_waiting(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(
                429,
                headers={"Retry-After": "3600"},
                json={"error": "limited"},
            )

        monkeypatch.setattr("app.integrations.freshservice.client.asyncio.sleep", fake_sleep)
        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_tickets()

        assert attempts == 1
        assert delays == []
        assert exc_info.value.code == "SOURCE_RATE_LIMITED"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_transient_server_error_uses_bounded_retries(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(503, json={"error": "unavailable"})

        monkeypatch.setattr("app.integrations.freshservice.client.asyncio.sleep", fake_sleep)
        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_tickets()

        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_UNAVAILABLE"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_connection_failure_maps_to_source_unavailable(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("connection failed", request=request)

        monkeypatch.setattr("app.integrations.freshservice.client.asyncio.sleep", fake_sleep)
        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_tickets()

        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_UNAVAILABLE"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_read_timeout_maps_to_source_unavailable_with_bounded_retries(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ReadTimeout("read timed out", request=request)

        monkeypatch.setattr("app.integrations.freshservice.client.asyncio.sleep", fake_sleep)
        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_tickets()

        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_UNAVAILABLE"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_malformed_ticket_payload_maps_to_bad_response_without_raw_body() -> None:
    async def run() -> None:
        marker = "raw-freshservice-marker-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=marker)

        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_tickets()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert exc_info.value.retryable is False
        assert marker not in str(exc_info.value)
        assert marker not in repr(exc_info.value)

    asyncio.run(run())


def test_blank_or_null_ticket_subject_normalizes_to_none() -> None:
    async def run() -> None:
        payloads = [ticket_payload(subject=None), ticket_payload(subject="   ")]

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"tickets": payloads})

        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        tickets = await client.list_tickets()

        assert [ticket.subject for ticket in tickets] == [None, None]

    asyncio.run(run())


def test_invalid_ticket_record_maps_to_bad_response() -> None:
    async def run() -> None:
        bad_ticket = ticket_payload(status=None)

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"tickets": [bad_ticket]})

        client = FreshserviceClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_tickets()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import IntegrationError, IntegrationErrorCode
from app.core.http import RETRY_DELAYS, create_http_client
from app.integrations.freshservice.models import (
    FreshserviceTicket,
    FreshserviceTicketPriority,
    FreshserviceTicketStatus,
)


FRESHSERVICE_TICKET_PAGE_SIZE = 100
FRESHSERVICE_MAX_TICKET_PAGES = 100
FRESHSERVICE_MAX_REQUEST_ATTEMPTS = 3
_FRESHSERVICE_RETRYABLE_STATUS_CODES = frozenset({502, 503, 504})

_STATUS_NAMES: dict[int, FreshserviceTicketStatus] = {
    2: "open",
    3: "pending",
    4: "resolved",
    5: "closed",
}
_PRIORITY_NAMES: dict[int, FreshserviceTicketPriority] = {
    1: "low",
    2: "medium",
    3: "high",
    4: "urgent",
}


class FreshserviceClient:
    """Read-only Freshservice API v2 client for incremental ticket retrieval."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        verify_tls: bool,
        ca_bundle: Path | None,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._verify_tls = verify_tls
        self._ca_bundle = ca_bundle
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> "FreshserviceClient":
        base_url = settings.freshservice_base_url
        api_key = settings.freshservice_api_key
        if (
            settings.integration_config_state("freshservice") != "configured"
            or base_url is None
            or api_key is None
        ):
            raise IntegrationError(
                source="freshservice",
                code="SOURCE_NOT_CONFIGURED",
                retryable=False,
            )
        if base_url.scheme != "https" or not (base_url.host or "").endswith(
            ".freshservice.com"
        ):
            raise IntegrationError(
                source="freshservice",
                code="SOURCE_BAD_RESPONSE",
                retryable=False,
            )

        return cls(
            base_url=str(base_url),
            api_key=api_key,
            verify_tls=settings.freshservice_verify_tls,
            ca_bundle=settings.freshservice_ca_bundle,
            timeout_seconds=settings.freshservice_timeout_seconds,
            transport=transport,
        )

    async def list_tickets(
        self,
        *,
        updated_since: datetime | None = None,
    ) -> list[FreshserviceTicket]:
        if updated_since is not None and updated_since.tzinfo is None:
            raise ValueError("updated_since must include timezone information")

        tickets: list[FreshserviceTicket] = []
        page = 1
        async with create_http_client(
            timeout_seconds=self._timeout_seconds,
            verify_tls=self._verify_tls,
            ca_bundle=self._ca_bundle,
            transport=self._transport,
        ) as client:
            for _ in range(FRESHSERVICE_MAX_TICKET_PAGES):
                response = await self._get_ticket_page(
                    client,
                    page=page,
                    updated_since=updated_since,
                )
                payload = self._parse_json_object(response)
                raw_tickets = payload.get("tickets")
                if not isinstance(raw_tickets, list):
                    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

                try:
                    tickets.extend(self._normalize_ticket(ticket) for ticket in raw_tickets)
                except (TypeError, ValueError, ValidationError) as exc:
                    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

                link_header = response.headers.get("Link", "")
                if 'rel="next"' not in link_header.lower():
                    return tickets
                if not raw_tickets:
                    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
                page += 1

        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

    async def _get_ticket_page(
        self,
        client: httpx.AsyncClient,
        *,
        page: int,
        updated_since: datetime | None,
    ) -> httpx.Response:
        params: dict[str, str | int] = {
            "page": page,
            "per_page": FRESHSERVICE_TICKET_PAGE_SIZE,
            "include": "stats",
        }
        if updated_since is not None:
            params["updated_since"] = updated_since.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        for attempt in range(FRESHSERVICE_MAX_REQUEST_ATTEMPTS):
            try:
                response = await client.get(
                    f"{self._base_url}/api/v2/tickets",
                    auth=httpx.BasicAuth(self._api_key.get_secret_value(), "X"),
                    headers={"Accept": "application/json"},
                    params=params,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt + 1 >= FRESHSERVICE_MAX_REQUEST_ATTEMPTS:
                    raise self._source_error("SOURCE_UNAVAILABLE", retryable=True) from exc
                await asyncio.sleep(RETRY_DELAYS[attempt])
                continue

            if response.status_code == 429:
                raise self._source_error("SOURCE_RATE_LIMITED", retryable=True)
            if (
                response.status_code in _FRESHSERVICE_RETRYABLE_STATUS_CODES
                and attempt + 1 < FRESHSERVICE_MAX_REQUEST_ATTEMPTS
            ):
                await asyncio.sleep(RETRY_DELAYS[attempt])
                continue

            self._raise_for_status(response)
            return response

        raise self._source_error("SOURCE_UNAVAILABLE", retryable=True)

    @staticmethod
    def _normalize_ticket(value: Any) -> FreshserviceTicket:
        if not isinstance(value, dict):
            raise TypeError("Freshservice ticket must be an object")

        status_code = _required_positive_int(value.get("status"))
        priority_code = _required_positive_int(value.get("priority"))
        stats = value.get("stats")
        if not isinstance(stats, dict):
            stats = {}

        return FreshserviceTicket(
            ticket_id=_required_positive_int(value.get("id")),
            subject=_required_string(value.get("subject")),
            status_code=status_code,
            status=cast(FreshserviceTicketStatus, _STATUS_NAMES.get(status_code, "unknown")),
            priority_code=priority_code,
            priority=cast(
                FreshserviceTicketPriority,
                _PRIORITY_NAMES.get(priority_code, "unknown"),
            ),
            ticket_type=_optional_string(value.get("type")),
            category=_optional_string(value.get("category")),
            sub_category=_optional_string(value.get("sub_category")),
            item_category=_optional_string(value.get("item_category")),
            requester_id=_optional_positive_int(value.get("requester_id")),
            requested_for_id=_optional_positive_int(value.get("requested_for_id")),
            responder_id=_optional_positive_int(value.get("responder_id")),
            group_id=_optional_positive_int(value.get("group_id")),
            department_id=_optional_positive_int(value.get("department_id")),
            workspace_id=_optional_positive_int(value.get("workspace_id")),
            source_code=_optional_positive_int(value.get("source")),
            due_by=_optional_datetime(value.get("due_by")),
            first_response_due_by=_optional_datetime(value.get("fr_due_by")),
            is_escalated=_optional_bool(value.get("is_escalated")),
            first_response_escalated=_optional_bool(value.get("fr_escalated")),
            created_at=_required_datetime(value.get("created_at")),
            updated_at=_required_datetime(value.get("updated_at")),
            resolved_at=_optional_datetime(stats.get("resolved_at")),
            closed_at=_optional_datetime(stats.get("closed_at")),
            first_responded_at=_optional_datetime(stats.get("first_responded_at")),
        )

    @staticmethod
    def _parse_json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise FreshserviceClient._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc
        if not isinstance(payload, dict):
            raise FreshserviceClient._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        return payload

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        if status in {401, 403}:
            raise FreshserviceClient._source_error("SOURCE_AUTH_FAILED", retryable=False)
        if status == 429:
            raise FreshserviceClient._source_error("SOURCE_RATE_LIMITED", retryable=True)
        if status >= 500:
            raise FreshserviceClient._source_error("SOURCE_UNAVAILABLE", retryable=True)
        raise FreshserviceClient._source_error("SOURCE_BAD_RESPONSE", retryable=False)

    @staticmethod
    def _source_error(code: IntegrationErrorCode, *, retryable: bool) -> IntegrationError:
        return IntegrationError(
            source="freshservice",
            code=code,
            retryable=retryable,
        )


def _required_string(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("required Freshservice string is invalid")
    text = value.strip()
    if not text:
        raise ValueError("required Freshservice string is blank")
    return text


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional Freshservice string is invalid")
    text = value.strip()
    return text or None


def _required_positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("required Freshservice integer is invalid")
    return value


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    return _required_positive_int(value)


def _optional_bool(value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError("Freshservice boolean is invalid")
    return value


def _required_datetime(value: Any) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise ValueError("required Freshservice datetime is invalid")
    return parsed


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Freshservice datetime is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Freshservice datetime is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import IntegrationError, IntegrationErrorCode
from app.core.http import create_http_client, request_with_retries
from app.integrations.wazuh.models import WazuhAgent, WazuhAgentStatus


WAZUH_AGENT_PAGE_SIZE = 500
WAZUH_MAX_AGENT_PAGES = 20
_WAZUH_KNOWN_AGENT_STATUSES = {
    "active",
    "pending",
    "never_connected",
    "disconnected",
}


class WazuhClient:
    """Read-only client for the Wazuh server API."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: SecretStr,
        verify_tls: bool,
        ca_bundle: Path | None,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
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
    ) -> "WazuhClient":
        base_url = settings.wazuh_base_url
        username = settings.wazuh_username
        password = settings.wazuh_password
        if (
            settings.wazuh_server_config_state() != "configured"
            or base_url is None
            or username is None
            or password is None
        ):
            raise IntegrationError(
                source="wazuh",
                code="SOURCE_NOT_CONFIGURED",
                retryable=False,
            )

        return cls(
            base_url=str(base_url),
            username=username,
            password=password,
            verify_tls=settings.wazuh_verify_tls,
            ca_bundle=settings.wazuh_ca_bundle,
            timeout_seconds=settings.wazuh_timeout_seconds,
            transport=transport,
        )

    async def list_agents(self) -> list[WazuhAgent]:
        async with create_http_client(
            timeout_seconds=self._timeout_seconds,
            verify_tls=self._verify_tls,
            ca_bundle=self._ca_bundle,
            transport=self._transport,
        ) as client:
            token = await self._authenticate(client)
            return await self._list_agents(client, token)

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        try:
            response = await request_with_retries(
                client,
                "POST",
                f"{self._base_url}/security/user/authenticate",
                auth=httpx.BasicAuth(
                    self._username,
                    self._password.get_secret_value(),
                ),
            )
        except httpx.RequestError as exc:
            raise self._source_error("SOURCE_UNAVAILABLE", retryable=True) from exc

        self._raise_for_status(response)
        payload = self._parse_json_object(response)
        data = payload.get("data")
        if payload.get("error") != 0 or not isinstance(data, dict):
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        return token

    async def _list_agents(
        self,
        client: httpx.AsyncClient,
        token: str,
    ) -> list[WazuhAgent]:
        agents: list[WazuhAgent] = []
        offset = 0

        for _ in range(WAZUH_MAX_AGENT_PAGES):
            payload = await self._get_agents_page(client, token, offset)
            data = payload.get("data")
            if payload.get("error") != 0 or not isinstance(data, dict):
                raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

            items = data.get("affected_items")
            total = data.get("total_affected_items")
            failed = data.get("total_failed_items", 0)
            if (
                not isinstance(items, list)
                or not isinstance(total, int)
                or total < 0
                or not isinstance(failed, int)
                or failed != 0
            ):
                raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

            try:
                agents.extend(self._normalize_agent(item) for item in items)
            except (KeyError, TypeError, ValueError, ValidationError) as exc:
                raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

            if len(agents) >= total:
                return agents[:total]
            if not items:
                raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

            offset += len(items)

        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

    async def _get_agents_page(
        self,
        client: httpx.AsyncClient,
        token: str,
        offset: int,
    ) -> dict[str, Any]:
        try:
            response = await request_with_retries(
                client,
                "GET",
                f"{self._base_url}/agents",
                retry_safe=True,
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": WAZUH_AGENT_PAGE_SIZE, "offset": offset},
            )
        except httpx.RequestError as exc:
            raise self._source_error("SOURCE_UNAVAILABLE", retryable=True) from exc

        self._raise_for_status(response)
        return self._parse_json_object(response)

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        if status in {401, 403}:
            raise self._source_error("SOURCE_AUTH_FAILED", retryable=False)
        if status == 429:
            raise self._source_error("SOURCE_RATE_LIMITED", retryable=True)
        if status >= 500:
            raise self._source_error("SOURCE_UNAVAILABLE", retryable=True)
        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

    def _parse_json_object(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc
        if not isinstance(payload, dict):
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        return payload

    @staticmethod
    def _normalize_agent(item: Any) -> WazuhAgent:
        if not isinstance(item, dict):
            raise TypeError("agent item must be an object")

        raw_status = item.get("status")
        status: WazuhAgentStatus
        if isinstance(raw_status, str) and raw_status in _WAZUH_KNOWN_AGENT_STATUSES:
            status = cast(WazuhAgentStatus, raw_status)
        else:
            status = "unknown"

        os_data = item.get("os")
        if not isinstance(os_data, dict):
            os_data = {}

        groups = item.get("group", [])
        if isinstance(groups, str):
            groups = [groups]
        elif not isinstance(groups, list):
            groups = []
        normalized_groups = [str(group) for group in groups if str(group).strip()]

        return WazuhAgent(
            agent_id=_required_string(item.get("id")),
            name=_required_string(item.get("name")),
            ip=_optional_string(item.get("ip")),
            status=status,
            manager=_optional_string(item.get("manager")),
            node_name=_optional_string(item.get("node_name")),
            groups=normalized_groups,
            last_keep_alive=_optional_datetime(item.get("lastKeepAlive")),
            os_name=_optional_string(os_data.get("name")),
            os_version=_optional_string(os_data.get("version")),
            os_platform=_optional_string(os_data.get("platform")),
            os_arch=_optional_string(os_data.get("arch")),
        )

    @staticmethod
    def _source_error(code: IntegrationErrorCode, *, retryable: bool) -> IntegrationError:
        return IntegrationError(
            source="wazuh",
            code=code,
            retryable=retryable,
        )


def _required_string(value: Any) -> str:
    if value is None:
        raise ValueError("required Wazuh field is missing")
    text = str(value).strip()
    if not text:
        raise ValueError("required Wazuh field is blank")
    return text


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import IntegrationError, IntegrationErrorCode
from app.core.http import create_http_client, request_with_retries
from app.integrations.zabbix.models import (
    ZabbixAvailability,
    ZabbixHost,
    ZabbixHostInterface,
    ZabbixInterfaceType,
)


ZABBIX_HOST_LIMIT = 5000
ZABBIX_HOST_SENTINEL_LIMIT = ZABBIX_HOST_LIMIT + 1
ZABBIX_INTERFACE_LIMIT = 32
ZABBIX_REQUEST_ID = 1

_INTERFACE_TYPES: dict[str, ZabbixInterfaceType] = {
    "1": "agent",
    "2": "snmp",
    "3": "ipmi",
    "4": "jmx",
}
_AVAILABILITY: dict[str, ZabbixAvailability] = {
    "0": "unknown",
    "1": "available",
    "2": "unavailable",
}


class ZabbixClient:
    """Read-only client for the Zabbix JSON-RPC API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_token: SecretStr,
        verify_tls: bool,
        ca_bundle: Path | None,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_token = api_token
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
    ) -> "ZabbixClient":
        base_url = settings.zabbix_base_url
        api_token = settings.zabbix_api_token
        if (
            settings.integration_config_state("zabbix") != "configured"
            or base_url is None
            or api_token is None
        ):
            raise IntegrationError(
                source="zabbix",
                code="SOURCE_NOT_CONFIGURED",
                retryable=False,
            )

        return cls(
            base_url=str(base_url),
            api_token=api_token,
            verify_tls=settings.zabbix_verify_tls,
            ca_bundle=settings.zabbix_ca_bundle,
            timeout_seconds=settings.zabbix_timeout_seconds,
            transport=transport,
        )

    async def list_hosts(self) -> list[ZabbixHost]:
        async with create_http_client(
            timeout_seconds=self._timeout_seconds,
            verify_tls=self._verify_tls,
            ca_bundle=self._ca_bundle,
            transport=self._transport,
        ) as client:
            try:
                response = await request_with_retries(
                    client,
                    "POST",
                    self._base_url,
                    retry_safe=True,
                    headers={
                        "Authorization": f"Bearer {self._api_token.get_secret_value()}",
                        "Content-Type": "application/json-rpc",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "method": "host.get",
                        "params": {
                            "output": [
                                "hostid",
                                "host",
                                "name",
                                "status",
                                "maintenance_status",
                            ],
                            "selectInterfaces": [
                                "interfaceid",
                                "type",
                                "main",
                                "useip",
                                "ip",
                                "dns",
                                "available",
                            ],
                            "limit": ZABBIX_HOST_SENTINEL_LIMIT,
                            "sortfield": "hostid",
                        },
                        "id": ZABBIX_REQUEST_ID,
                    },
                )
            except httpx.RequestError as exc:
                raise self._source_error("SOURCE_UNAVAILABLE", retryable=True) from exc

        self._raise_for_status(response)
        payload = self._parse_payload(response)
        if payload.get("jsonrpc") != "2.0" or payload.get("id") != ZABBIX_REQUEST_ID:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        has_result = "result" in payload
        has_error = "error" in payload
        if has_result == has_error:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        if has_error:
            self._raise_jsonrpc_error(payload.get("error"))

        result = payload.get("result")
        if not isinstance(result, list):
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        if len(result) > ZABBIX_HOST_LIMIT:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        try:
            return [self._normalize_host(item) for item in result]
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

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

    def _parse_payload(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc
        if not isinstance(payload, dict):
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        return payload

    def _raise_jsonrpc_error(self, error: Any) -> None:
        if not isinstance(error, dict):
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        detail = error.get("data")
        if isinstance(detail, str) and "not authorized" in detail.casefold():
            raise self._source_error("SOURCE_AUTH_FAILED", retryable=False)
        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

    @staticmethod
    def _source_error(
        code: IntegrationErrorCode,
        *,
        retryable: bool,
    ) -> IntegrationError:
        return IntegrationError(
            source="zabbix",
            code=code,
            retryable=retryable,
        )

    @staticmethod
    def _normalize_host(item: Any) -> ZabbixHost:
        if not isinstance(item, dict):
            raise TypeError("host item must be an object")
        interfaces = item.get("interfaces", [])
        if not isinstance(interfaces, list):
            raise TypeError("interfaces must be a list")
        if len(interfaces) > ZABBIX_INTERFACE_LIMIT:
            raise ValueError("too many Zabbix host interfaces")

        return ZabbixHost(
            host_id=_required_string(item.get("hostid")),
            technical_name=_required_string(item.get("host")),
            name=_required_string(item.get("name")),
            enabled=_binary_bool(item.get("status"), true_value="0"),
            in_maintenance=_binary_bool(
                item.get("maintenance_status"),
                true_value="1",
            ),
            interfaces=[ZabbixClient._normalize_interface(value) for value in interfaces],
        )

    @staticmethod
    def _normalize_interface(item: Any) -> ZabbixHostInterface:
        if not isinstance(item, dict):
            raise TypeError("interface item must be an object")
        use_ip = _binary_bool(item.get("useip"), true_value="1")
        address = item.get("ip") if use_ip else item.get("dns")
        return ZabbixHostInterface(
            interface_id=_required_string(item.get("interfaceid")),
            type=_INTERFACE_TYPES.get(str(item.get("type")), "unknown"),
            is_main=_binary_bool(item.get("main"), true_value="1"),
            address=_optional_string(address),
            availability=_AVAILABILITY.get(str(item.get("available")), "unknown"),
        )


def _required_string(value: Any) -> str:
    if value is None:
        raise ValueError("required Zabbix field is missing")
    text = str(value).strip()
    if not text:
        raise ValueError("required Zabbix field is blank")
    return text


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _binary_bool(value: Any, *, true_value: str) -> bool:
    text = str(value)
    if text not in {"0", "1"}:
        raise ValueError("Zabbix binary field must be 0 or 1")
    return text == true_value

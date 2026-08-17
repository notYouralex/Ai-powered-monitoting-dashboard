from __future__ import annotations

import asyncio
from datetime import datetime, timezone
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
    ZabbixProblem,
    ZabbixProblemHost,
    ZabbixProblemSeverity,
    ZabbixResourcePressure,
    ZabbixResourceTrend,
    ZabbixTopologyEdge,
    ZabbixTopologyMap,
    ZabbixTopologyNode,
)
from app.integrations.zabbix.resource_pressure import (
    normalize_resource_pressure,
    select_resource_trend_items,
)
from app.integrations.zabbix.trends import completed_trend_window, normalize_resource_trends


ZABBIX_HOST_LIMIT = 5000
ZABBIX_HOST_SENTINEL_LIMIT = ZABBIX_HOST_LIMIT + 1
ZABBIX_INTERFACE_LIMIT = 32
ZABBIX_PROBLEM_LIMIT = 1000
ZABBIX_PROBLEM_SENTINEL_LIMIT = ZABBIX_PROBLEM_LIMIT + 1
ZABBIX_PROBLEM_HOST_LIMIT = 32
ZABBIX_RESOURCE_ITEM_LIMIT = 10000
ZABBIX_RESOURCE_ITEM_SENTINEL_LIMIT = ZABBIX_RESOURCE_ITEM_LIMIT + 1
ZABBIX_RESOURCE_HOST_LIMIT = 5000
ZABBIX_TREND_HOST_LIMIT = 10
ZABBIX_TREND_SELECTION_LIMIT = 30
ZABBIX_TREND_ROW_LIMIT = 720
ZABBIX_TREND_ROW_SENTINEL_LIMIT = ZABBIX_TREND_ROW_LIMIT + 1
ZABBIX_MAP_LIMIT = 100
ZABBIX_MAP_SENTINEL_LIMIT = ZABBIX_MAP_LIMIT + 1
ZABBIX_MAP_NODE_LIMIT = 1000
ZABBIX_MAP_EDGE_LIMIT = 2000
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
_PROBLEM_SEVERITIES: dict[str, ZabbixProblemSeverity] = {
    "0": "not_classified",
    "1": "information",
    "2": "warning",
    "3": "average",
    "4": "high",
    "5": "disaster",
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
        result = await self._read_jsonrpc(
            method="host.get",
            params={
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
        )
        if len(result) > ZABBIX_HOST_LIMIT:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        try:
            return [self._normalize_host(item) for item in result]
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

    async def list_topology_maps(self) -> list[ZabbixTopologyMap]:
        result = await self._read_jsonrpc(
            method="map.get",
            params={
                "output": ["sysmapid", "name", "width", "height"],
                "selectSelements": [
                    "selementid",
                    "elementtype",
                    "elements",
                    "label",
                    "x",
                    "y",
                ],
                "selectLinks": [
                    "linkid",
                    "selementid1",
                    "selementid2",
                    "label",
                ],
                "sortfield": "name",
                "limit": ZABBIX_MAP_SENTINEL_LIMIT,
            },
        )
        if len(result) > ZABBIX_MAP_LIMIT:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        try:
            return [self._normalize_topology_map(item) for item in result]
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

    async def list_active_problems(self) -> list[ZabbixProblem]:
        problem_items = await self._read_jsonrpc(
            method="problem.get",
            params={
                "output": [
                    "eventid",
                    "objectid",
                    "clock",
                    "name",
                    "acknowledged",
                    "severity",
                    "suppressed",
                ],
                "recent": False,
                "source": 0,
                "object": 0,
                "sortfield": "eventid",
                "sortorder": "DESC",
                "limit": ZABBIX_PROBLEM_SENTINEL_LIMIT,
            },
        )
        if len(problem_items) > ZABBIX_PROBLEM_LIMIT:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        if not problem_items:
            return []

        try:
            trigger_ids = self._unique_problem_trigger_ids(problem_items)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

        trigger_items = await self._read_jsonrpc(
            method="trigger.get",
            params={
                "triggerids": trigger_ids,
                "output": ["triggerid"],
                "selectHosts": ["hostid", "host", "name"],
            },
        )

        try:
            hosts_by_trigger = self._normalize_trigger_hosts(
                trigger_items,
                requested=trigger_ids,
            )
            return [
                self._normalize_problem(
                    item,
                    hosts_by_trigger=hosts_by_trigger,
                )
                for item in problem_items
            ]
        except (
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            OSError,
            ValidationError,
        ) as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

    async def list_resource_pressure(self) -> list[ZabbixResourcePressure]:
        async def read_prefix(prefix: str) -> list[Any]:
            return await self._read_jsonrpc(
                method="item.get",
                params={
                    "output": ["itemid", "hostid", "key_", "lastvalue", "lastclock"],
                    "monitored": True,
                    "filter": {"state": "0"},
                    "search": {"key_": prefix},
                    "startSearch": True,
                    "sortfield": "itemid",
                    "limit": ZABBIX_RESOURCE_ITEM_SENTINEL_LIMIT,
                },
            )

        cpu_items, memory_size_items, memory_util_items, disk_items = await asyncio.gather(
            read_prefix("system.cpu.util"),
            read_prefix("vm.memory.size"),
            read_prefix("vm.memory.util"),
            read_prefix("vfs.fs.size"),
        )
        if any(
            len(items) > ZABBIX_RESOURCE_ITEM_LIMIT
            for items in (cpu_items, memory_size_items, memory_util_items, disk_items)
        ):
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        memory_items = [*memory_size_items, *memory_util_items]
        if len(memory_items) > ZABBIX_RESOURCE_ITEM_LIMIT:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        try:
            resource_pressure = normalize_resource_pressure(
                cpu_items,
                memory_items,
                disk_items,
            )
            if len(resource_pressure) > ZABBIX_RESOURCE_HOST_LIMIT:
                raise ValueError("too many normalized Zabbix resource hosts")
            return resource_pressure
        except (
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            OSError,
            ValidationError,
        ) as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

    async def list_resource_trends(
        self,
        host_ids: list[str],
    ) -> list[ZabbixResourceTrend]:
        try:
            requested_host_ids = self._normalize_trend_host_ids(host_ids)
        except (TypeError, ValueError) as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc
        if not requested_host_ids:
            return []

        async def read_prefix(prefix: str) -> list[Any]:
            return await self._read_jsonrpc(
                method="item.get",
                params={
                    "output": ["itemid", "hostid", "key_", "lastvalue", "lastclock"],
                    "hostids": requested_host_ids,
                    "monitored": True,
                    "filter": {"state": "0"},
                    "search": {"key_": prefix},
                    "startSearch": True,
                    "sortfield": "itemid",
                    "limit": ZABBIX_RESOURCE_ITEM_SENTINEL_LIMIT,
                },
            )

        cpu_items, memory_size_items, memory_util_items, disk_items = await asyncio.gather(
            read_prefix("system.cpu.util"),
            read_prefix("vm.memory.size"),
            read_prefix("vm.memory.util"),
            read_prefix("vfs.fs.size"),
        )
        if any(
            len(items) > ZABBIX_RESOURCE_ITEM_LIMIT
            for items in (cpu_items, memory_size_items, memory_util_items, disk_items)
        ):
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        memory_items = [*memory_size_items, *memory_util_items]
        if len(memory_items) > ZABBIX_RESOURCE_ITEM_LIMIT:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        try:
            selections = select_resource_trend_items(
                cpu_items,
                memory_items,
                disk_items,
                requested_host_ids,
            )
            if len(selections) > ZABBIX_TREND_SELECTION_LIMIT:
                raise ValueError("too many selected Zabbix trend items")
            if not selections:
                return []
            time_from, time_till = completed_trend_window()
        except (
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            OSError,
            ValidationError,
        ) as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

        trend_items = await self._read_jsonrpc(
            method="trend.get",
            params={
                "output": ["itemid", "clock", "value_avg"],
                "itemids": [selection.item_id for selection in selections],
                "time_from": time_from,
                "time_till": time_till,
                "limit": ZABBIX_TREND_ROW_SENTINEL_LIMIT,
            },
        )
        if len(trend_items) > ZABBIX_TREND_ROW_LIMIT:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        try:
            return normalize_resource_trends(
                trend_items,
                selections,
                time_from=time_from,
                time_till=time_till,
                host_rank=requested_host_ids,
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            OSError,
            ValidationError,
        ) as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

    async def _read_jsonrpc(
        self,
        *,
        method: str,
        params: dict[str, Any],
    ) -> list[Any]:
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
                        "method": method,
                        "params": params,
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
        return result

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
    def _unique_problem_trigger_ids(items: list[Any]) -> list[str]:
        trigger_ids: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                raise TypeError("problem item must be an object")
            trigger_id = _required_string(item.get("objectid"))
            if trigger_id not in seen:
                seen.add(trigger_id)
                trigger_ids.append(trigger_id)
        return trigger_ids

    @staticmethod
    def _normalize_trend_host_ids(host_ids: list[str]) -> list[str]:
        if not isinstance(host_ids, list):
            raise TypeError("Zabbix trend host IDs must be a list")
        requested: list[str] = []
        seen: set[str] = set()
        for value in host_ids:
            if not isinstance(value, str):
                raise TypeError("Zabbix trend host ID must be a string")
            host_id = value.strip()
            if not host_id:
                raise ValueError("Zabbix trend host ID is blank")
            if len(host_id) > 64:
                raise ValueError("Zabbix trend host ID is too long")
            if host_id in seen:
                continue
            seen.add(host_id)
            requested.append(host_id)
            if len(requested) > ZABBIX_TREND_HOST_LIMIT:
                raise ValueError("too many Zabbix trend hosts")
        return requested

    @staticmethod
    def _normalize_problem_hosts(items: list[Any]) -> list[ZabbixProblemHost]:
        hosts: list[ZabbixProblemHost] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                raise TypeError("trigger host item must be an object")
            host_id = _required_string(item.get("hostid"))
            if host_id in seen:
                continue
            seen.add(host_id)
            hosts.append(
                ZabbixProblemHost(
                    host_id=host_id,
                    technical_name=_required_string(item.get("host")),
                    name=_required_string(item.get("name")),
                )
            )
        return hosts

    @staticmethod
    def _normalize_trigger_hosts(
        items: list[Any],
        *,
        requested: list[str],
    ) -> dict[str, list[ZabbixProblemHost]]:
        if len(items) > len(requested):
            raise ValueError("too many Zabbix trigger records")

        requested_set = set(requested)
        seen: set[str] = set()
        hosts_by_trigger: dict[str, list[ZabbixProblemHost]] = {}
        for item in items:
            if not isinstance(item, dict):
                raise TypeError("trigger item must be an object")
            trigger_id = _required_string(item.get("triggerid"))
            if trigger_id not in requested_set:
                raise ValueError("unrequested Zabbix trigger record")
            if trigger_id in seen:
                raise ValueError("duplicate Zabbix trigger record")

            raw_hosts = item.get("hosts")
            if not isinstance(raw_hosts, list):
                raise TypeError("trigger hosts must be a list")
            if len(raw_hosts) > ZABBIX_PROBLEM_HOST_LIMIT:
                raise ValueError("too many hosts for Zabbix trigger")

            seen.add(trigger_id)
            hosts_by_trigger[trigger_id] = ZabbixClient._normalize_problem_hosts(
                raw_hosts
            )
        return hosts_by_trigger

    @staticmethod
    def _normalize_problem(
        item: Any,
        *,
        hosts_by_trigger: dict[str, list[ZabbixProblemHost]],
    ) -> ZabbixProblem:
        if not isinstance(item, dict):
            raise TypeError("problem item must be an object")
        trigger_id = _required_string(item.get("objectid"))
        return ZabbixProblem(
            event_id=_required_string(item.get("eventid")),
            trigger_id=trigger_id,
            name=_required_string(item.get("name")),
            severity=_PROBLEM_SEVERITIES.get(str(item.get("severity")), "unknown"),
            started_at=datetime.fromtimestamp(
                int(item.get("clock")),
                tz=timezone.utc,
            ),
            acknowledged=_binary_bool(item.get("acknowledged"), true_value="1"),
            suppressed=_binary_bool(item.get("suppressed"), true_value="1"),
            hosts=hosts_by_trigger.get(trigger_id, []),
        )

    @staticmethod
    def _normalize_topology_map(item: Any) -> ZabbixTopologyMap:
        if not isinstance(item, dict):
            raise TypeError("map item must be an object")
        selements = item.get("selements", [])
        links = item.get("links", [])
        if not isinstance(selements, list) or not isinstance(links, list):
            raise TypeError("map elements and links must be lists")
        if len(selements) > ZABBIX_MAP_NODE_LIMIT:
            raise ValueError("too many Zabbix map elements")
        if len(links) > ZABBIX_MAP_EDGE_LIMIT:
            raise ValueError("too many Zabbix map links")

        nodes: list[ZabbixTopologyNode] = []
        node_ids: set[str] = set()
        for selement in selements:
            if not isinstance(selement, dict):
                raise TypeError("map element must be an object")
            if str(selement.get("elementtype")) != "0":
                continue
            node = ZabbixClient._normalize_topology_node(selement)
            if node.node_id in node_ids:
                raise ValueError("duplicate Zabbix map element ID")
            node_ids.add(node.node_id)
            nodes.append(node)

        edges: list[ZabbixTopologyEdge] = []
        edge_ids: set[str] = set()
        for link in links:
            if not isinstance(link, dict):
                raise TypeError("map link must be an object")
            source = _required_string(link.get("selementid1"))
            target = _required_string(link.get("selementid2"))
            if source not in node_ids or target not in node_ids:
                continue
            edge_id = _required_string(link.get("linkid"))
            if edge_id in edge_ids:
                raise ValueError("duplicate Zabbix map link ID")
            edge_ids.add(edge_id)
            edges.append(
                ZabbixTopologyEdge(
                    edge_id=edge_id,
                    source=source,
                    target=target,
                    label=_optional_string(link.get("label")),
                )
            )

        return ZabbixTopologyMap(
            map_id=_required_string(item.get("sysmapid")),
            name=_required_string(item.get("name")),
            width=_bounded_nonnegative_int(item.get("width"), minimum=1),
            height=_bounded_nonnegative_int(item.get("height"), minimum=1),
            nodes=nodes,
            edges=edges,
        )

    @staticmethod
    def _normalize_topology_node(item: dict[str, Any]) -> ZabbixTopologyNode:
        elements = item.get("elements")
        if not isinstance(elements, list) or len(elements) != 1:
            raise ValueError("host map element must contain exactly one host")
        host = elements[0]
        if not isinstance(host, dict):
            raise TypeError("host map element data must be an object")
        host_id = _required_string(host.get("hostid"))
        return ZabbixTopologyNode(
            node_id=_required_string(item.get("selementid")),
            host_id=host_id,
            title=_optional_string(item.get("label")) or host_id,
            status="unknown",
            x=_bounded_nonnegative_int(item.get("x")),
            y=_bounded_nonnegative_int(item.get("y")),
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


def _bounded_nonnegative_int(value: Any, *, minimum: int = 0) -> int:
    number = int(_required_string(value))
    if number < minimum or number > 100000:
        raise ValueError("Zabbix numeric field is out of bounds")
    return number


def _binary_bool(value: Any, *, true_value: str) -> bool:
    text = str(value)
    if text not in {"0", "1"}:
        raise ValueError("Zabbix binary field must be 0 or 1")
    return text == true_value

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import IntegrationError, IntegrationErrorCode
from app.core.http import create_http_client, request_with_retries
from app.integrations.wazuh.models import (
    WazuhAlert,
    WazuhAlertSearchResult,
    WazuhNamedCount,
    WazuhTrendPoint,
)


WAZUH_ALERT_INDEX = "wazuh-alerts*"
WAZUH_RECENT_ALERT_LIMIT = 50
WAZUH_TOP_AGENT_LIMIT = 10
WAZUH_MAX_TREND_BUCKETS = 512
_ALERT_SOURCE_FIELDS = (
    "timestamp",
    "rule.id",
    "rule.level",
    "rule.description",
    "rule.groups",
    "agent.id",
    "agent.name",
)


class WazuhIndexerClient:
    """Read-only Wazuh indexer client used for alert searches."""

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
    ) -> "WazuhIndexerClient":
        base_url = settings.wazuh_indexer_base_url
        username = settings.wazuh_indexer_username
        password = settings.wazuh_indexer_password
        if (
            settings.wazuh_indexer_config_state() != "configured"
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
            verify_tls=settings.wazuh_indexer_verify_tls,
            ca_bundle=settings.wazuh_indexer_ca_bundle,
            timeout_seconds=settings.wazuh_indexer_timeout_seconds,
            transport=transport,
        )

    async def search_alerts(
        self,
        start: datetime,
        end: datetime,
        *,
        trend_interval: str,
    ) -> WazuhAlertSearchResult:
        body = self._build_search_body(start, end, trend_interval=trend_interval)
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
                    f"{self._base_url}/{WAZUH_ALERT_INDEX}/_search",
                    retry_safe=True,
                    auth=httpx.BasicAuth(
                        self._username,
                        self._password.get_secret_value(),
                    ),
                    params={
                        "ignore_unavailable": "true",
                        "allow_no_indices": "true",
                        "allow_partial_search_results": "false",
                    },
                    json=body,
                )
            except httpx.RequestError as exc:
                raise self._source_error("SOURCE_UNAVAILABLE", retryable=True) from exc

        self._raise_for_status(response)
        payload = self._parse_json_object(response)
        return self._normalize_search_response(payload)

    @staticmethod
    def _build_search_body(
        start: datetime,
        end: datetime,
        *,
        trend_interval: str,
    ) -> dict[str, Any]:
        return {
            "size": WAZUH_RECENT_ALERT_LIMIT,
            "track_total_hits": True,
            "_source": list(_ALERT_SOURCE_FIELDS),
            "query": {
                "range": {
                    "timestamp": {
                        "gte": start.isoformat(),
                        "lte": end.isoformat(),
                    }
                }
            },
            "sort": [{"timestamp": {"order": "desc"}}],
            "aggs": {
                "severity_levels": {
                    "terms": {
                        "field": "rule.level",
                        "size": 17,
                    }
                },
                "top_agents": {
                    "terms": {
                        "field": "agent.name",
                        "size": WAZUH_TOP_AGENT_LIMIT,
                        "order": {"_count": "desc"},
                    }
                },
                "alert_trend": {
                    "date_histogram": {
                        "field": "timestamp",
                        "fixed_interval": trend_interval,
                        "min_doc_count": 0,
                        "extended_bounds": {
                            "min": start.isoformat(),
                            "max": end.isoformat(),
                        },
                    }
                },
            },
        }

    def _normalize_search_response(self, payload: dict[str, Any]) -> WazuhAlertSearchResult:
        if payload.get("timed_out") is True:
            raise self._source_error("SOURCE_UNAVAILABLE", retryable=True)

        shards = payload.get("_shards")
        if not isinstance(shards, dict) or shards.get("failed") != 0:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        hits = payload.get("hits")
        aggregations = payload.get("aggregations")
        if not isinstance(hits, dict) or not isinstance(aggregations, dict):
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        total_alerts = self._parse_total_hits(hits.get("total"))
        raw_hits = hits.get("hits")
        if not isinstance(raw_hits, list):
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

        try:
            alerts = [self._normalize_alert_hit(hit) for hit in raw_hits]
            severity_levels = self._parse_severity_buckets(aggregations.get("severity_levels"))
            top_agents = self._parse_named_buckets(aggregations.get("top_agents"))
            trend = self._parse_trend_buckets(aggregations.get("alert_trend"))
            return WazuhAlertSearchResult(
                total_alerts=total_alerts,
                severity_levels=severity_levels,
                top_agents=top_agents,
                trend=trend,
                alerts=alerts,
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

    @staticmethod
    def _parse_total_hits(value: Any) -> int:
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, dict):
            total = value.get("value")
            if isinstance(total, int) and total >= 0:
                return total
        raise ValueError("invalid total hit count")

    @staticmethod
    def _normalize_alert_hit(hit: Any) -> WazuhAlert:
        if not isinstance(hit, dict):
            raise TypeError("alert hit must be an object")
        source = hit.get("_source")
        if not isinstance(source, dict):
            raise TypeError("alert source must be an object")

        rule = source.get("rule")
        if not isinstance(rule, dict):
            raise TypeError("alert rule must be an object")

        agent = source.get("agent")
        if not isinstance(agent, dict):
            agent = {}

        groups = rule.get("groups", [])
        if isinstance(groups, str):
            groups = [groups]
        elif not isinstance(groups, list):
            groups = []

        return WazuhAlert(
            timestamp=_required_datetime(source.get("timestamp")),
            rule_id=_required_string(rule.get("id")),
            rule_level=_required_int(rule.get("level")),
            description=_required_string(rule.get("description")),
            agent_id=_optional_string(agent.get("id")),
            agent_name=_optional_string(agent.get("name")),
            groups=[str(group).strip() for group in groups if str(group).strip()],
        )

    @staticmethod
    def _parse_severity_buckets(value: Any) -> dict[int, int]:
        buckets = _require_buckets(value)
        result: dict[int, int] = {}
        for bucket in buckets:
            level = _required_int(bucket.get("key"))
            count = _required_nonnegative_int(bucket.get("doc_count"))
            if not 0 <= level <= 16:
                raise ValueError("Wazuh rule level is out of range")
            result[level] = count
        return result

    @staticmethod
    def _parse_named_buckets(value: Any) -> list[WazuhNamedCount]:
        buckets = _require_buckets(value)
        return [
            WazuhNamedCount(
                name=_required_string(bucket.get("key")),
                count=_required_nonnegative_int(bucket.get("doc_count")),
            )
            for bucket in buckets[:WAZUH_TOP_AGENT_LIMIT]
        ]

    @staticmethod
    def _parse_trend_buckets(value: Any) -> list[WazuhTrendPoint]:
        buckets = _require_buckets(value)
        if len(buckets) > WAZUH_MAX_TREND_BUCKETS:
            raise ValueError("too many Wazuh trend buckets")
        return [
            WazuhTrendPoint(
                timestamp=_required_datetime(bucket.get("key_as_string")),
                count=_required_nonnegative_int(bucket.get("doc_count")),
            )
            for bucket in buckets
        ]

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
    def _source_error(code: IntegrationErrorCode, *, retryable: bool) -> IntegrationError:
        return IntegrationError(
            source="wazuh",
            code=code,
            retryable=retryable,
        )


def _require_buckets(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        raise TypeError("aggregation must be an object")
    buckets = value.get("buckets")
    if not isinstance(buckets, list) or not all(isinstance(bucket, dict) for bucket in buckets):
        raise TypeError("aggregation buckets must be objects")
    return buckets


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


def _required_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise ValueError("required Wazuh integer is invalid")


def _required_nonnegative_int(value: Any) -> int:
    number = _required_int(value)
    if number < 0:
        raise ValueError("count must be non-negative")
    return number


def _required_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("required Wazuh timestamp is invalid")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("required Wazuh timestamp is invalid") from exc

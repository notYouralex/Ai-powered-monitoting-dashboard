"""Pure helpers for bounded Zabbix resource trend windows and normalization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from app.integrations.zabbix.models import (
    ResourceTrendMetric,
    ZabbixResourceTrend,
    ZabbixResourceTrendPoint,
)
from app.integrations.zabbix.resource_pressure import ResourceTrendItemSelection


_METRIC_ORDER: dict[ResourceTrendMetric, int] = {
    "cpu": 0,
    "memory": 1,
    "disk": 2,
}


def completed_trend_window(now: datetime | None = None) -> tuple[int, int]:
    value = datetime.now(timezone.utc) if now is None else now
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Zabbix trend window requires timezone-aware datetime")
    current_hour = value.astimezone(timezone.utc).replace(
        minute=0,
        second=0,
        microsecond=0,
    )
    time_from = int((current_hour - timedelta(hours=24)).timestamp())
    time_till = int(current_hour.timestamp()) - 1
    return time_from, time_till


def normalize_resource_trends(
    raw_rows: list[Any],
    selections: list[ResourceTrendItemSelection],
    *,
    time_from: int,
    time_till: int,
    host_rank: list[str],
) -> list[ZabbixResourceTrend]:
    if time_till < time_from:
        raise ValueError("invalid Zabbix trend window")

    host_order = {host_id: index for index, host_id in enumerate(host_rank)}
    selection_by_item: dict[str, ResourceTrendItemSelection] = {}
    for selection in selections:
        item_id = _required_id(selection.item_id, field="itemid")
        _required_id(selection.host_id, field="hostid")
        if selection.host_id not in host_order:
            raise ValueError("Zabbix trend selection host is not ranked")
        if item_id in selection_by_item:
            raise ValueError("duplicate Zabbix trend item selection")
        if selection.metric == "disk" and not selection.filesystem:
            raise ValueError("Zabbix disk trend requires filesystem")
        if selection.metric != "disk" and selection.filesystem is not None:
            raise ValueError("non-disk Zabbix trend cannot include filesystem")
        selection_by_item[item_id] = selection

    points_by_item: dict[str, list[ZabbixResourceTrendPoint]] = {}
    seen: set[tuple[str, int]] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise TypeError("Zabbix trend row must be an object")
        item_id = _required_id(raw.get("itemid"), field="itemid")
        selection = selection_by_item.get(item_id)
        if selection is None:
            raise ValueError("unrequested Zabbix trend item")

        clock = _required_clock(raw.get("clock"))
        if clock % 3600 != 0:
            raise ValueError("Zabbix trend clock must be hour-aligned")
        if clock < time_from or clock > time_till:
            raise ValueError("Zabbix trend clock is outside requested window")
        key = (item_id, clock)
        if key in seen:
            raise ValueError("duplicate Zabbix trend row")
        seen.add(key)

        value = _percentage(raw.get("value_avg"))
        used_percent = 100.0 - value if selection.invert else value
        points = points_by_item.setdefault(item_id, [])
        points.append(
            ZabbixResourceTrendPoint(
                observed_at=datetime.fromtimestamp(clock, tz=timezone.utc),
                average_used_percent=used_percent,
            )
        )
        if len(points) > 24:
            raise ValueError("Zabbix trend series exceeds 24 points")

    rows: list[ZabbixResourceTrend] = []
    for item_id, selection in selection_by_item.items():
        points = points_by_item.get(item_id, [])
        if not points:
            continue
        points.sort(key=lambda point: point.observed_at)
        rows.append(
            ZabbixResourceTrend(
                host_id=selection.host_id,
                metric=selection.metric,
                filesystem=selection.filesystem,
                points=points,
            )
        )

    rows.sort(
        key=lambda row: (
            host_order[row.host_id],
            _METRIC_ORDER[row.metric],
            row.filesystem or "",
        )
    )
    return rows


def _required_id(value: Any, *, field: str) -> str:
    if value is None:
        raise ValueError(f"Zabbix trend {field} is missing")
    text = str(value).strip()
    if not text:
        raise ValueError(f"Zabbix trend {field} is blank")
    if len(text) > 64:
        raise ValueError(f"Zabbix trend {field} is too long")
    return text


def _required_clock(value: Any) -> int:
    if value is None:
        raise ValueError("Zabbix trend clock is missing")
    clock = int(value)
    if clock <= 0:
        raise ValueError("Zabbix trend clock must be positive")
    return clock


def _percentage(value: Any) -> float:
    if value is None:
        raise ValueError("Zabbix trend percentage is missing")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise ValueError("Zabbix trend percentage is invalid")
    return number

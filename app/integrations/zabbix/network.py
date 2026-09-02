import csv
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from app.integrations.zabbix.models import (
    NetworkLiveMetric,
    ZabbixNetworkLivePoint,
    ZabbixNetworkLiveSeries,
)


@dataclass(frozen=True)
class _Candidate:
    item_id: str
    host_id: str
    metric: NetworkLiveMetric
    interface: str | None
    clock: int
    observed_at: datetime
    value: float
    exact_latency_key: bool = False


def normalize_network_live(
    latency_items: list[Any],
    inbound_items: list[Any],
    outbound_items: list[Any],
) -> list[ZabbixNetworkLiveSeries]:
    selected: dict[tuple[str, NetworkLiveMetric, str | None], _Candidate] = {}

    for item in latency_items:
        key = _item_key(item)
        if key != "icmppingsec" and not key.startswith("icmppingsec["):
            continue
        candidate = _latency_candidate(item, key=key)
        if candidate is not None:
            _select(selected, candidate)

    for metric, items, prefix in (
        ("inbound", inbound_items, "net.if.in"),
        ("outbound", outbound_items, "net.if.out"),
    ):
        for item in items:
            key = _item_key(item)
            params = _key_params(key, prefix)
            if params is None:
                continue
            candidate = _bandwidth_candidate(item, metric=metric, params=params)
            if candidate is not None:
                _select(selected, candidate)

    rows = [
        ZabbixNetworkLiveSeries(
            host_id=candidate.host_id,
            metric=candidate.metric,
            interface=candidate.interface,
            points=[
                ZabbixNetworkLivePoint(
                    observed_at=candidate.observed_at,
                    value=candidate.value,
                )
            ],
        )
        for candidate in selected.values()
    ]
    rows.sort(key=lambda row: (row.host_id, row.metric, row.interface or ""))
    return rows


def _select(
    selected: dict[tuple[str, NetworkLiveMetric, str | None], _Candidate],
    candidate: _Candidate,
) -> None:
    key = (candidate.host_id, candidate.metric, candidate.interface)
    current = selected.get(key)
    if current is None or _is_preferred(candidate, current):
        selected[key] = candidate


def _is_preferred(candidate: _Candidate, current: _Candidate) -> bool:
    if candidate.metric == "latency" and candidate.exact_latency_key != current.exact_latency_key:
        return candidate.exact_latency_key
    if candidate.clock != current.clock:
        return candidate.clock > current.clock
    return _item_id_sort_key(candidate.item_id) < _item_id_sort_key(current.item_id)


def _latency_candidate(item: Any, *, key: str) -> _Candidate | None:
    if not isinstance(item, dict):
        raise TypeError("Zabbix network item must be an object")
    units = item.get("units")
    if units not in {"s", "ms"}:
        return None
    base = _numeric_candidate(item)
    if base is None:
        return None
    value = base.value * 1000.0 if units == "s" else base.value
    return _Candidate(
        item_id=base.item_id,
        host_id=base.host_id,
        metric="latency",
        interface=None,
        clock=base.clock,
        observed_at=base.observed_at,
        value=value,
        exact_latency_key=key == "icmppingsec",
    )


def _bandwidth_candidate(
    item: Any,
    *,
    metric: Literal["inbound", "outbound"],
    params: list[str],
) -> _Candidate | None:
    if not 1 <= len(params) <= 2:
        return None
    interface = params[0].strip()
    mode = params[1].strip().casefold() if len(params) == 2 else ""
    if not interface or len(interface) > 256 or mode not in {"", "bytes"}:
        return None
    if not isinstance(item, dict):
        raise TypeError("Zabbix network item must be an object")
    units = item.get("units")
    if units not in {"bps", "Bps"}:
        return None
    base = _numeric_candidate(item)
    if base is None:
        return None
    value = base.value * 8.0 if units == "Bps" else base.value
    return _Candidate(
        item_id=base.item_id,
        host_id=base.host_id,
        metric=metric,
        interface=interface,
        clock=base.clock,
        observed_at=base.observed_at,
        value=value,
    )


def _numeric_candidate(item: dict[str, Any]) -> _Candidate | None:
    raw_value = item.get("lastvalue")
    raw_clock = item.get("lastclock")
    if raw_value is None or not str(raw_value).strip() or str(raw_clock) == "0":
        return None

    item_id = _required_id(item.get("itemid"), field="itemid")
    host_id = _required_id(item.get("hostid"), field="hostid")
    clock = int(raw_clock)
    if clock <= 0:
        raise ValueError("Zabbix network clock must be positive")
    value = float(raw_value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Zabbix network value is invalid")
    return _Candidate(
        item_id=item_id,
        host_id=host_id,
        metric="latency",
        interface=None,
        clock=clock,
        observed_at=datetime.fromtimestamp(clock, tz=timezone.utc),
        value=value,
    )


def _item_key(item: Any) -> str:
    if not isinstance(item, dict):
        raise TypeError("Zabbix network item must be an object")
    value = item.get("key_")
    return value.strip() if isinstance(value, str) else ""


def _key_params(key: str, prefix: str) -> list[str] | None:
    marker = f"{prefix}["
    if not key.startswith(marker) or not key.endswith("]"):
        return None
    try:
        return next(
            csv.reader(
                [key[len(marker) : -1]],
                quotechar='"',
                escapechar="\\",
                skipinitialspace=False,
            )
        )
    except (csv.Error, StopIteration) as exc:
        raise ValueError("invalid Zabbix network item key") from exc


def _required_id(value: Any, *, field: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text or len(text) > 64:
        raise ValueError(f"invalid Zabbix network {field}")
    return text


def _item_id_sort_key(item_id: str) -> tuple[int, int | str]:
    if item_id.isdigit():
        return (0, int(item_id))
    return (1, item_id)

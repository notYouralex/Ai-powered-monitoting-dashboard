"""Pure normalization helpers for Zabbix resource-pressure items."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any

from app.integrations.zabbix.models import ZabbixDiskPressure, ZabbixResourcePressure


MAX_FILESYSTEMS_PER_HOST = 64


@dataclass(frozen=True)
class _Candidate:
    item_id: str
    host_id: str
    used_percent: float
    clock: int
    observed_at: datetime
    mode: str
    filesystem: str | None = None


def normalize_resource_pressure(
    cpu_items: list[Any],
    memory_items: list[Any],
    disk_items: list[Any],
) -> list[ZabbixResourcePressure]:
    cpu_by_host: dict[str, _Candidate] = {}
    memory_by_host_mode: dict[tuple[str, str], _Candidate] = {}
    disk_by_host_fs_mode: dict[tuple[str, str, str], _Candidate] = {}

    for item in cpu_items:
        key = _item_key(item)
        if not _is_supported_cpu_key(key):
            continue
        candidate = _candidate(item, mode="idle", invert=True)
        if candidate is None:
            continue
        current = cpu_by_host.get(candidate.host_id)
        if current is None or _is_newer_candidate(candidate, current):
            cpu_by_host[candidate.host_id] = candidate

    for item in memory_items:
        key = _item_key(item)
        mode = _memory_mode(key)
        if mode is None:
            continue
        candidate = _candidate(item, mode=mode, invert=mode == "pavailable")
        if candidate is None:
            continue
        lookup = (candidate.host_id, mode)
        current = memory_by_host_mode.get(lookup)
        if current is None or _is_newer_candidate(candidate, current):
            memory_by_host_mode[lookup] = candidate

    for item in disk_items:
        key = _item_key(item)
        parsed = _disk_key(key)
        if parsed is None:
            continue
        filesystem, mode = parsed
        candidate = _candidate(
            item,
            mode=mode,
            invert=mode == "pfree",
            filesystem=filesystem,
        )
        if candidate is None:
            continue
        lookup = (candidate.host_id, filesystem, mode)
        current = disk_by_host_fs_mode.get(lookup)
        if current is None or _is_newer_candidate(candidate, current):
            disk_by_host_fs_mode[lookup] = candidate

    memory_by_host = _prefer_memory_modes(memory_by_host_mode)
    disks_by_host = _build_disks(disk_by_host_fs_mode)

    host_ids = set(cpu_by_host) | set(memory_by_host) | set(disks_by_host)
    rows: list[ZabbixResourcePressure] = []
    for host_id in sorted(host_ids, key=_id_sort_key):
        cpu = cpu_by_host.get(host_id)
        memory = memory_by_host.get(host_id)
        rows.append(
            ZabbixResourcePressure(
                host_id=host_id,
                cpu_used_percent=None if cpu is None else cpu.used_percent,
                cpu_observed_at=None if cpu is None else cpu.observed_at,
                memory_used_percent=None if memory is None else memory.used_percent,
                memory_observed_at=None if memory is None else memory.observed_at,
                disks=disks_by_host.get(host_id, []),
            )
        )
    return rows


def _item_key(item: Any) -> str:
    if not isinstance(item, dict):
        raise TypeError("Zabbix resource item must be an object")
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
        raise ValueError("invalid Zabbix item key") from exc


def _is_supported_cpu_key(key: str) -> bool:
    params = _key_params(key, "system.cpu.util")
    if params is None or not 2 <= len(params) <= 4:
        return False
    cpu = params[0].strip().casefold()
    state = params[1].strip().casefold()
    mode = params[2].strip().casefold() if len(params) >= 3 else ""
    logical = params[3].strip().casefold() if len(params) >= 4 else ""
    return (
        cpu in {"", "all"}
        and state == "idle"
        and mode in {"", "avg1"}
        and logical in {"", "logical"}
    )


def _memory_mode(key: str) -> str | None:
    params = _key_params(key, "vm.memory.size")
    if params is None or len(params) != 1:
        return None
    mode = params[0].strip().casefold()
    return mode if mode in {"pused", "pavailable"} else None


def _disk_key(key: str) -> tuple[str, str] | None:
    params = _key_params(key, "vfs.fs.size")
    if params is None or len(params) != 2:
        return None
    filesystem = params[0].strip()
    mode = params[1].strip().casefold()
    if mode not in {"pused", "pfree"}:
        return None
    if not filesystem:
        raise ValueError("Zabbix filesystem is blank")
    if len(filesystem) > 512:
        raise ValueError("Zabbix filesystem is too long")
    return filesystem, mode


def _candidate(
    item: dict[str, Any],
    *,
    mode: str,
    invert: bool,
    filesystem: str | None = None,
) -> _Candidate | None:
    raw_value = item.get("lastvalue")
    raw_clock = item.get("lastclock")
    if raw_value is None or not str(raw_value).strip() or str(raw_clock) == "0":
        return None

    item_id = _required_id(item.get("itemid"), field="itemid")
    host_id = _required_id(item.get("hostid"), field="hostid")
    clock = int(raw_clock)
    if clock <= 0:
        raise ValueError("Zabbix resource clock must be positive")
    observed_at = datetime.fromtimestamp(clock, tz=timezone.utc)

    value = float(raw_value)
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("Zabbix resource percentage is invalid")
    used_percent = 100.0 - value if invert else value

    return _Candidate(
        item_id=item_id,
        host_id=host_id,
        used_percent=used_percent,
        clock=clock,
        observed_at=observed_at,
        mode=mode,
        filesystem=filesystem,
    )


def _required_id(value: Any, *, field: str) -> str:
    if value is None:
        raise ValueError(f"Zabbix {field} is missing")
    text = str(value).strip()
    if not text:
        raise ValueError(f"Zabbix {field} is blank")
    if len(text) > 64:
        raise ValueError(f"Zabbix {field} is too long")
    return text


def _is_newer_candidate(candidate: _Candidate, current: _Candidate) -> bool:
    if candidate.clock != current.clock:
        return candidate.clock > current.clock
    return _id_sort_key(candidate.item_id) < _id_sort_key(current.item_id)


def _prefer_memory_modes(
    candidates: dict[tuple[str, str], _Candidate],
) -> dict[str, _Candidate]:
    host_ids = {host_id for host_id, _ in candidates}
    selected: dict[str, _Candidate] = {}
    for host_id in host_ids:
        candidate = candidates.get((host_id, "pused"))
        if candidate is None:
            candidate = candidates.get((host_id, "pavailable"))
        if candidate is not None:
            selected[host_id] = candidate
    return selected


def _build_disks(
    candidates: dict[tuple[str, str, str], _Candidate],
) -> dict[str, list[ZabbixDiskPressure]]:
    host_filesystems = {(host_id, filesystem) for host_id, filesystem, _ in candidates}
    selected_by_host: dict[str, list[ZabbixDiskPressure]] = {}
    for host_id, filesystem in host_filesystems:
        candidate = candidates.get((host_id, filesystem, "pused"))
        if candidate is None:
            candidate = candidates.get((host_id, filesystem, "pfree"))
        if candidate is None:
            continue
        selected_by_host.setdefault(host_id, []).append(
            ZabbixDiskPressure(
                filesystem=filesystem,
                used_percent=candidate.used_percent,
                observed_at=candidate.observed_at,
            )
        )

    for disks in selected_by_host.values():
        if len(disks) > MAX_FILESYSTEMS_PER_HOST:
            raise ValueError("too many Zabbix filesystems for one host")
        disks.sort(key=lambda disk: disk.filesystem)
    return selected_by_host


def _id_sort_key(value: str) -> tuple[int, int | str]:
    if value.isdigit():
        return (0, int(value))
    return (1, value)

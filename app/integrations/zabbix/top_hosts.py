"""Pure ranking for the most affected enabled Zabbix hosts."""

from __future__ import annotations

from app.integrations.zabbix.models import (
    ResourceTrendMetric,
    ZabbixHost,
    ZabbixProblem,
    ZabbixProblemSeverity,
    ZabbixResourcePressure,
    ZabbixTopAffectedHost,
)


_SEVERITY_RANK: dict[ZabbixProblemSeverity, int] = {
    "not_classified": 1,
    "information": 2,
    "warning": 3,
    "average": 4,
    "high": 5,
    "disaster": 6,
    "unknown": 7,
}


def rank_top_affected_hosts(
    hosts: list[ZabbixHost],
    active_problems: list[ZabbixProblem],
    resource_pressure: list[ZabbixResourcePressure],
    *,
    limit: int = 10,
) -> list[ZabbixTopAffectedHost]:
    problems_by_host: dict[str, list[ZabbixProblem]] = {}
    for problem in active_problems:
        for problem_host in problem.hosts:
            problems_by_host.setdefault(problem_host.host_id, []).append(problem)

    resources_by_host = {pressure.host_id: pressure for pressure in resource_pressure}
    ranked: list[tuple[tuple[object, ...], ZabbixTopAffectedHost]] = []
    for host in hosts:
        if not host.enabled:
            continue

        problems = problems_by_host.get(host.host_id, [])
        unavailable = sum(
            1 for interface in host.interfaces if interface.availability == "unavailable"
        )
        pressure = resources_by_host.get(host.host_id)
        if not problems and unavailable == 0 and not _has_resource_metric(pressure):
            continue

        severity = _highest_severity(problems)
        peak_percent, peak_resource, peak_filesystem = _peak_resource(pressure)
        row = ZabbixTopAffectedHost(
            host_id=host.host_id,
            technical_name=host.technical_name,
            name=host.name,
            highest_problem_severity=severity,
            active_problem_count=len(problems),
            unavailable_interface_count=unavailable,
            peak_resource_percent=peak_percent,
            peak_resource=peak_resource,
            peak_filesystem=peak_filesystem,
        )
        rank_key = (
            -(_SEVERITY_RANK.get(severity, 0) if severity is not None else 0),
            -unavailable,
            -len(problems),
            -(peak_percent if peak_percent is not None else -1.0),
            _id_sort_key(host.host_id),
        )
        ranked.append((rank_key, row))

    ranked.sort(key=lambda value: value[0])
    return [row for _, row in ranked[:limit]]


def _highest_severity(problems: list[ZabbixProblem]) -> ZabbixProblemSeverity | None:
    if not problems:
        return None
    return max(problems, key=lambda problem: _SEVERITY_RANK[problem.severity]).severity


def _has_resource_metric(pressure: ZabbixResourcePressure | None) -> bool:
    return pressure is not None and (
        pressure.cpu_used_percent is not None
        or pressure.memory_used_percent is not None
        or bool(pressure.disks)
    )


def _peak_resource(
    pressure: ZabbixResourcePressure | None,
) -> tuple[float | None, ResourceTrendMetric | None, str | None]:
    if pressure is None:
        return None, None, None

    candidates: list[tuple[float, ResourceTrendMetric, str | None]] = []
    if pressure.cpu_used_percent is not None:
        candidates.append((pressure.cpu_used_percent, "cpu", None))
    if pressure.memory_used_percent is not None:
        candidates.append((pressure.memory_used_percent, "memory", None))
    for disk in sorted(pressure.disks, key=lambda value: value.filesystem):
        candidates.append((disk.used_percent, "disk", disk.filesystem))

    if not candidates:
        return None, None, None

    selected = candidates[0]
    for candidate in candidates[1:]:
        if candidate[0] > selected[0]:
            selected = candidate
    return selected


def _id_sort_key(value: str) -> tuple[int, int | str]:
    if value.isdigit():
        return (0, int(value))
    return (1, value)

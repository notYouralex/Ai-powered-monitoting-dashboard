import asyncio
from datetime import datetime, timezone
from time import perf_counter

from app.contracts import IntegrationHealthSummary
from app.core.errors import IntegrationError
from app.integrations.zabbix.client import ZabbixClient
from app.integrations.zabbix.models import (
    ZabbixDashboardResponse,
    ZabbixDashboardSummary,
    ZabbixHost,
    ZabbixProblem,
    ZabbixResourcePressure,
    ZabbixTopologyMap,
    ZabbixTopologyNode,
)
from app.integrations.zabbix.top_hosts import rank_top_affected_hosts


class ZabbixDashboardService:
    """Compose normalized Zabbix monitoring data for dashboards."""

    def __init__(self, *, client: ZabbixClient) -> None:
        self._client = client

    async def get_dashboard(self) -> ZabbixDashboardResponse:
        started = perf_counter()
        hosts, active_problems, resource_pressure = await asyncio.gather(
            self._client.list_hosts(),
            self._client.list_active_problems(),
            self._client.list_resource_pressure(),
        )
        top_affected_hosts = rank_top_affected_hosts(
            hosts,
            active_problems,
            resource_pressure,
        )
        resource_trends = await self._client.list_resource_trends(
            [row.host_id for row in top_affected_hosts]
        )
        topology_warning: str | None = None
        try:
            topology_maps = await self._client.list_topology_maps()
        except IntegrationError:
            topology_maps = []
            topology_warning = (
                "Zabbix topology maps are unavailable; core monitoring data remains available."
            )
        else:
            topology_maps = _enrich_topology_maps(topology_maps, hosts, active_problems)

        observed_at = datetime.now(timezone.utc)
        response_time_ms = max(0, int((perf_counter() - started) * 1000))
        return ZabbixDashboardResponse(
            observed_at=observed_at,
            health=IntegrationHealthSummary(
                source="zabbix",
                status="healthy",
                observed_at=observed_at,
                last_success_at=observed_at,
                response_time_ms=response_time_ms,
                is_stale=False,
                warnings=[],
            ),
            summary=_build_summary(hosts, active_problems, resource_pressure),
            hosts=hosts,
            active_problems=active_problems,
            resource_pressure=resource_pressure,
            top_affected_hosts=top_affected_hosts,
            resource_trends=resource_trends,
            topology_maps=topology_maps,
            warnings=_build_warnings(
                hosts,
                active_problems,
                resource_pressure,
                topology_warning=topology_warning,
            ),
        )


def _enrich_topology_maps(
    topology_maps: list[ZabbixTopologyMap],
    hosts: list[ZabbixHost],
    active_problems: list[ZabbixProblem],
) -> list[ZabbixTopologyMap]:
    hosts_by_id = {host.host_id: host for host in hosts}
    problem_counts: dict[str, int] = {}
    for problem in active_problems:
        for problem_host in problem.hosts:
            problem_counts[problem_host.host_id] = problem_counts.get(problem_host.host_id, 0) + 1

    enriched: list[ZabbixTopologyMap] = []
    for topology in topology_maps:
        nodes: list[ZabbixTopologyNode] = []
        for node in topology.nodes:
            host = hosts_by_id.get(node.host_id)
            title = node.title
            status = "unknown"
            if host is not None:
                if title == node.host_id:
                    title = host.name
                status = _topology_host_status(host)
            nodes.append(
                node.model_copy(
                    update={
                        "title": title,
                        "status": status,
                        "active_problem_count": problem_counts.get(node.host_id, 0),
                    }
                )
            )
        enriched.append(topology.model_copy(update={"nodes": nodes}))
    return enriched


def _topology_host_status(host: ZabbixHost) -> str:
    if not host.enabled:
        return "disabled"
    if host.in_maintenance:
        return "maintenance"
    availability = {interface.availability for interface in host.interfaces}
    if "unavailable" in availability:
        return "unavailable"
    if "available" in availability:
        return "available"
    return "unknown"


def _build_summary(
    hosts: list[ZabbixHost],
    active_problems: list[ZabbixProblem],
    resource_pressure: list[ZabbixResourcePressure],
) -> ZabbixDashboardSummary:
    enabled = sum(1 for host in hosts if host.enabled)
    maintenance = sum(1 for host in hosts if host.in_maintenance)
    availability = {"available": 0, "unavailable": 0, "unknown": 0}
    for host in hosts:
        for interface in host.interfaces:
            availability[interface.availability] += 1

    severity = {
        "not_classified": 0,
        "information": 0,
        "warning": 0,
        "average": 0,
        "high": 0,
        "disaster": 0,
        "unknown": 0,
    }
    for problem in active_problems:
        severity[problem.severity] += 1

    return ZabbixDashboardSummary(
        hosts_total=len(hosts),
        hosts_enabled=enabled,
        hosts_disabled=len(hosts) - enabled,
        hosts_in_maintenance=maintenance,
        interfaces_available=availability["available"],
        interfaces_unavailable=availability["unavailable"],
        interfaces_unknown=availability["unknown"],
        problems_total=len(active_problems),
        problems_not_classified=severity["not_classified"],
        problems_information=severity["information"],
        problems_warning=severity["warning"],
        problems_average=severity["average"],
        problems_high=severity["high"],
        problems_disaster=severity["disaster"],
        problems_unknown=severity["unknown"],
        problems_unacknowledged=sum(
            1 for problem in active_problems if not problem.acknowledged
        ),
        problems_suppressed=sum(1 for problem in active_problems if problem.suppressed),
        resource_hosts_total=len(resource_pressure),
        resource_hosts_with_cpu=sum(
            1 for pressure in resource_pressure if pressure.cpu_used_percent is not None
        ),
        resource_hosts_with_memory=sum(
            1 for pressure in resource_pressure if pressure.memory_used_percent is not None
        ),
        resource_hosts_with_disk=sum(1 for pressure in resource_pressure if pressure.disks),
    )


def _build_warnings(
    hosts: list[ZabbixHost],
    active_problems: list[ZabbixProblem],
    resource_pressure: list[ZabbixResourcePressure],
    *,
    topology_warning: str | None = None,
) -> list[str]:
    warnings: list[str] = []

    unmapped = sum(1 for problem in active_problems if not problem.hosts)
    if unmapped == 1:
        warnings.append(
            "1 active Zabbix problem could not be mapped to a current host."
        )
    elif unmapped > 1:
        warnings.append(
            f"{unmapped} active Zabbix problems could not be mapped to a current host."
        )

    by_host = {pressure.host_id: pressure for pressure in resource_pressure}
    enabled_hosts = [host for host in hosts if host.enabled]
    missing_cpu = sum(
        1
        for host in enabled_hosts
        if by_host.get(host.host_id) is None
        or by_host[host.host_id].cpu_used_percent is None
    )
    missing_memory = sum(
        1
        for host in enabled_hosts
        if by_host.get(host.host_id) is None
        or by_host[host.host_id].memory_used_percent is None
    )
    missing_disk = sum(
        1
        for host in enabled_hosts
        if by_host.get(host.host_id) is None or not by_host[host.host_id].disks
    )

    _append_resource_warning(warnings, missing_cpu, "CPU")
    _append_resource_warning(warnings, missing_memory, "memory")
    _append_resource_warning(warnings, missing_disk, "disk")
    if topology_warning is not None:
        warnings.append(topology_warning)
    return warnings


def _append_resource_warning(
    warnings: list[str],
    count: int,
    metric: str,
) -> None:
    if count == 0:
        return
    if count == 1:
        warnings.append(
            f"1 enabled Zabbix host has no current {metric} utilization metric."
        )
        return
    warnings.append(
        f"{count} enabled Zabbix hosts have no current {metric} utilization metric."
    )

import asyncio
from datetime import datetime, timezone
from time import perf_counter

from app.contracts import IntegrationHealthSummary
from app.integrations.zabbix.client import ZabbixClient
from app.integrations.zabbix.models import (
    ZabbixDashboardResponse,
    ZabbixDashboardSummary,
    ZabbixHost,
    ZabbixProblem,
)


class ZabbixDashboardService:
    """Compose normalized Zabbix monitoring data for dashboards."""

    def __init__(self, *, client: ZabbixClient) -> None:
        self._client = client

    async def get_dashboard(self) -> ZabbixDashboardResponse:
        started = perf_counter()
        hosts, active_problems = await asyncio.gather(
            self._client.list_hosts(),
            self._client.list_active_problems(),
        )
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
            summary=_build_summary(hosts, active_problems),
            hosts=hosts,
            active_problems=active_problems,
            warnings=_build_warnings(active_problems),
        )


def _build_summary(
    hosts: list[ZabbixHost],
    active_problems: list[ZabbixProblem],
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
    )


def _build_warnings(active_problems: list[ZabbixProblem]) -> list[str]:
    unmapped = sum(1 for problem in active_problems if not problem.hosts)
    if unmapped == 0:
        return []
    if unmapped == 1:
        return ["1 active Zabbix problem could not be mapped to a current host."]
    return [f"{unmapped} active Zabbix problems could not be mapped to a current host."]

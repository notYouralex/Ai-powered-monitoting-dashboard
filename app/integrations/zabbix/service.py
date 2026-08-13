from datetime import datetime, timezone
from time import perf_counter

from app.contracts import IntegrationHealthSummary
from app.integrations.zabbix.client import ZabbixClient
from app.integrations.zabbix.models import ZabbixDashboardResponse, ZabbixDashboardSummary, ZabbixHost


class ZabbixDashboardService:
    """Compose normalized Zabbix host availability data for dashboards."""

    def __init__(self, *, client: ZabbixClient) -> None:
        self._client = client

    async def get_dashboard(self) -> ZabbixDashboardResponse:
        started = perf_counter()
        hosts = await self._client.list_hosts()
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
            summary=_build_summary(hosts),
            hosts=hosts,
        )


def _build_summary(hosts: list[ZabbixHost]) -> ZabbixDashboardSummary:
    enabled = sum(1 for host in hosts if host.enabled)
    maintenance = sum(1 for host in hosts if host.in_maintenance)
    availability = {"available": 0, "unavailable": 0, "unknown": 0}
    for host in hosts:
        for interface in host.interfaces:
            availability[interface.availability] += 1
    return ZabbixDashboardSummary(
        hosts_total=len(hosts),
        hosts_enabled=enabled,
        hosts_disabled=len(hosts) - enabled,
        hosts_in_maintenance=maintenance,
        interfaces_available=availability["available"],
        interfaces_unavailable=availability["unavailable"],
        interfaces_unknown=availability["unknown"],
    )

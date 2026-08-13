import asyncio

from app.integrations.zabbix.models import ZabbixHost, ZabbixHostInterface
from app.integrations.zabbix.service import ZabbixDashboardService


def host(
    host_id: str,
    *,
    enabled: bool,
    in_maintenance: bool = False,
    availability: str = "unknown",
) -> ZabbixHost:
    return ZabbixHost(
        host_id=host_id,
        technical_name=f"host-{host_id}",
        name=f"Host {host_id}",
        enabled=enabled,
        in_maintenance=in_maintenance,
        interfaces=[
            ZabbixHostInterface(
                interface_id=f"if-{host_id}",
                type="agent",
                is_main=True,
                address=f"10.0.0.{host_id}",
                availability=availability,
            )
        ],
    )


class FakeZabbixClient:
    def __init__(self, hosts: list[ZabbixHost]) -> None:
        self.hosts = hosts
        self.calls = 0

    async def list_hosts(self) -> list[ZabbixHost]:
        self.calls += 1
        return self.hosts


def test_dashboard_service_builds_host_and_interface_summary() -> None:
    async def run() -> None:
        hosts = [
            host("1", enabled=True, availability="available"),
            host("2", enabled=False, availability="unavailable"),
            host("3", enabled=True, in_maintenance=True, availability="unknown"),
        ]
        client = FakeZabbixClient(hosts)
        service = ZabbixDashboardService(client=client)

        response = await service.get_dashboard()

        assert client.calls == 1
        assert response.source == "zabbix"
        assert response.health.source == "zabbix"
        assert response.health.status == "healthy"
        assert response.health.is_stale is False
        assert response.health.last_success_at == response.observed_at
        assert response.summary.hosts_total == 3
        assert response.summary.hosts_enabled == 2
        assert response.summary.hosts_disabled == 1
        assert response.summary.hosts_in_maintenance == 1
        assert response.summary.interfaces_available == 1
        assert response.summary.interfaces_unavailable == 1
        assert response.summary.interfaces_unknown == 1
        assert response.hosts == hosts

    asyncio.run(run())


def test_dashboard_service_handles_empty_host_snapshot() -> None:
    async def run() -> None:
        client = FakeZabbixClient([])
        service = ZabbixDashboardService(client=client)

        response = await service.get_dashboard()

        assert response.health.status == "healthy"
        assert response.summary.hosts_total == 0
        assert response.summary.hosts_enabled == 0
        assert response.summary.hosts_disabled == 0
        assert response.summary.hosts_in_maintenance == 0
        assert response.summary.interfaces_available == 0
        assert response.summary.interfaces_unavailable == 0
        assert response.summary.interfaces_unknown == 0
        assert response.hosts == []

    asyncio.run(run())

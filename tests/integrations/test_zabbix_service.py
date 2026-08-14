import asyncio
from datetime import datetime, timezone

import pytest

from app.core.errors import IntegrationError
from app.integrations.zabbix.models import (
    ZabbixDiskPressure,
    ZabbixHost,
    ZabbixHostInterface,
    ZabbixProblem,
    ZabbixProblemHost,
    ZabbixResourcePressure,
    ZabbixResourceTrend,
    ZabbixResourceTrendPoint,
)
from app.integrations.zabbix.service import ZabbixDashboardService


STARTED_AT = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)


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


def problem(
    event_id: str,
    *,
    severity: str,
    acknowledged: bool = False,
    suppressed: bool = False,
    mapped: bool = True,
    host_id: str = "10001",
) -> ZabbixProblem:
    hosts = []
    if mapped:
        hosts = [
            ZabbixProblemHost(
                host_id=host_id,
                technical_name=f"host-{host_id}",
                name=f"Host {host_id}",
            )
        ]
    return ZabbixProblem(
        event_id=event_id,
        trigger_id=f"trigger-{event_id}",
        name=f"Problem {event_id}",
        severity=severity,
        started_at=STARTED_AT,
        acknowledged=acknowledged,
        suppressed=suppressed,
        hosts=hosts,
    )


def pressure(
    host_id: str,
    *,
    cpu: float | None = None,
    memory: float | None = None,
    disk: float | None = None,
) -> ZabbixResourcePressure:
    disks = []
    if disk is not None:
        disks = [
            ZabbixDiskPressure(
                filesystem="/",
                used_percent=disk,
                observed_at=STARTED_AT,
            )
        ]
    return ZabbixResourcePressure(
        host_id=host_id,
        cpu_used_percent=cpu,
        cpu_observed_at=STARTED_AT if cpu is not None else None,
        memory_used_percent=memory,
        memory_observed_at=STARTED_AT if memory is not None else None,
        disks=disks,
    )


def trend(host_id: str, *, metric: str = "cpu", value: float = 50) -> ZabbixResourceTrend:
    return ZabbixResourceTrend(
        host_id=host_id,
        metric=metric,
        filesystem="/" if metric == "disk" else None,
        points=[
            ZabbixResourceTrendPoint(
                observed_at=STARTED_AT,
                average_used_percent=value,
            )
        ],
    )


class FakeZabbixClient:
    def __init__(
        self,
        hosts: list[ZabbixHost],
        active_problems: list[ZabbixProblem] | None = None,
        resource_pressure: list[ZabbixResourcePressure] | None = None,
        resource_trends: list[ZabbixResourceTrend] | None = None,
        trend_error: IntegrationError | None = None,
    ) -> None:
        self.hosts = hosts
        self.active_problems = [] if active_problems is None else active_problems
        self.resource_pressure = [] if resource_pressure is None else resource_pressure
        self.resource_trends = [] if resource_trends is None else resource_trends
        self.trend_error = trend_error
        self.host_calls = 0
        self.problem_calls = 0
        self.resource_calls = 0
        self.trend_calls: list[list[str]] = []

    async def list_hosts(self) -> list[ZabbixHost]:
        self.host_calls += 1
        return self.hosts

    async def list_active_problems(self) -> list[ZabbixProblem]:
        self.problem_calls += 1
        return self.active_problems

    async def list_resource_pressure(self) -> list[ZabbixResourcePressure]:
        self.resource_calls += 1
        return self.resource_pressure

    async def list_resource_trends(self, host_ids: list[str]) -> list[ZabbixResourceTrend]:
        self.trend_calls.append(host_ids)
        if self.trend_error is not None:
            raise self.trend_error
        return self.resource_trends


class CoordinatedClient:
    def __init__(self) -> None:
        self.host_started = asyncio.Event()
        self.problem_started = asyncio.Event()
        self.resource_started = asyncio.Event()

    async def _wait_for_all(self) -> None:
        await asyncio.wait_for(self.host_started.wait(), timeout=0.2)
        await asyncio.wait_for(self.problem_started.wait(), timeout=0.2)
        await asyncio.wait_for(self.resource_started.wait(), timeout=0.2)

    async def list_hosts(self) -> list[ZabbixHost]:
        self.host_started.set()
        await self._wait_for_all()
        return []

    async def list_active_problems(self) -> list[ZabbixProblem]:
        self.problem_started.set()
        await self._wait_for_all()
        return []

    async def list_resource_pressure(self) -> list[ZabbixResourcePressure]:
        self.resource_started.set()
        await self._wait_for_all()
        return []

    async def list_resource_trends(self, host_ids: list[str]) -> list[ZabbixResourceTrend]:
        assert host_ids == []
        return []


def test_dashboard_service_fetches_hosts_problems_and_resources_concurrently() -> None:
    async def run() -> None:
        service = ZabbixDashboardService(client=CoordinatedClient())

        response = await service.get_dashboard()

        assert response.summary.hosts_total == 0
        assert response.summary.problems_total == 0
        assert response.summary.resource_hosts_total == 0
        assert response.active_problems == []
        assert response.resource_pressure == []

    asyncio.run(run())


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

        assert client.host_calls == 1
        assert client.problem_calls == 1
        assert client.resource_calls == 1
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


def test_dashboard_service_builds_problem_summary_and_returns_active_problems() -> None:
    async def run() -> None:
        problems = [
            problem("1", severity="not_classified"),
            problem("2", severity="information", acknowledged=True),
            problem("3", severity="warning", suppressed=True),
            problem("4", severity="average"),
            problem("5", severity="high", acknowledged=True, suppressed=True),
            problem("6", severity="disaster"),
            problem("7", severity="unknown"),
        ]
        client = FakeZabbixClient([], problems)
        service = ZabbixDashboardService(client=client)

        response = await service.get_dashboard()

        assert response.summary.problems_total == 7
        assert response.summary.problems_not_classified == 1
        assert response.summary.problems_information == 1
        assert response.summary.problems_warning == 1
        assert response.summary.problems_average == 1
        assert response.summary.problems_high == 1
        assert response.summary.problems_disaster == 1
        assert response.summary.problems_unknown == 1
        assert response.summary.problems_unacknowledged == 5
        assert response.summary.problems_suppressed == 2
        assert response.active_problems == problems
        assert response.warnings == []

    asyncio.run(run())


def test_dashboard_service_handles_empty_snapshot() -> None:
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
        assert response.summary.problems_total == 0
        assert response.summary.problems_not_classified == 0
        assert response.summary.problems_information == 0
        assert response.summary.problems_warning == 0
        assert response.summary.problems_average == 0
        assert response.summary.problems_high == 0
        assert response.summary.problems_disaster == 0
        assert response.summary.problems_unknown == 0
        assert response.summary.problems_unacknowledged == 0
        assert response.summary.problems_suppressed == 0
        assert response.summary.resource_hosts_total == 0
        assert response.summary.resource_hosts_with_cpu == 0
        assert response.summary.resource_hosts_with_memory == 0
        assert response.summary.resource_hosts_with_disk == 0
        assert response.hosts == []
        assert response.active_problems == []
        assert response.resource_pressure == []
        assert response.warnings == []

    asyncio.run(run())


def test_dashboard_service_warns_for_one_unmapped_problem() -> None:
    async def run() -> None:
        client = FakeZabbixClient(
            [],
            [problem("1", severity="high", mapped=False)],
        )
        service = ZabbixDashboardService(client=client)

        response = await service.get_dashboard()

        assert response.health.status == "healthy"
        assert response.health.warnings == []
        assert response.warnings == [
            "1 active Zabbix problem could not be mapped to a current host."
        ]

    asyncio.run(run())


def test_dashboard_service_warns_once_for_multiple_unmapped_problems() -> None:
    async def run() -> None:
        client = FakeZabbixClient(
            [],
            [
                problem("1", severity="warning", mapped=False),
                problem("2", severity="average", mapped=False),
                problem("3", severity="high", mapped=True),
            ],
        )
        service = ZabbixDashboardService(client=client)

        response = await service.get_dashboard()

        assert response.health.status == "healthy"
        assert response.health.warnings == []
        assert response.warnings == [
            "2 active Zabbix problems could not be mapped to a current host."
        ]

    asyncio.run(run())


def test_dashboard_service_builds_resource_pressure_summary() -> None:
    async def run() -> None:
        resources = [
            pressure("1", cpu=70, memory=50, disk=80),
            pressure("2", cpu=30, memory=40),
            pressure("3", disk=90),
        ]
        client = FakeZabbixClient([], resource_pressure=resources)
        service = ZabbixDashboardService(client=client)

        response = await service.get_dashboard()

        assert response.summary.resource_hosts_total == 3
        assert response.summary.resource_hosts_with_cpu == 2
        assert response.summary.resource_hosts_with_memory == 2
        assert response.summary.resource_hosts_with_disk == 2
        assert response.resource_pressure == resources
        assert response.warnings == []

    asyncio.run(run())


def test_dashboard_service_warns_for_missing_enabled_resource_metrics() -> None:
    async def run() -> None:
        hosts = [
            host("1", enabled=True),
            host("2", enabled=True),
            host("3", enabled=False),
        ]
        problems = [problem("1", severity="high", mapped=False)]
        resources = [
            pressure("1", cpu=55),
            pressure("3", memory=25, disk=30),
        ]
        client = FakeZabbixClient(hosts, problems, resources)
        service = ZabbixDashboardService(client=client)

        response = await service.get_dashboard()

        assert response.health.status == "healthy"
        assert response.health.warnings == []
        assert response.warnings == [
            "1 active Zabbix problem could not be mapped to a current host.",
            "1 enabled Zabbix host has no current CPU utilization metric.",
            "2 enabled Zabbix hosts have no current memory utilization metric.",
            "2 enabled Zabbix hosts have no current disk utilization metric.",
        ]

    asyncio.run(run())


def test_dashboard_service_ranks_top_hosts_then_fetches_trends_in_rank_order() -> None:
    async def run() -> None:
        hosts = [
            host("1", enabled=True, availability="available"),
            host("2", enabled=True, availability="available"),
            host("3", enabled=True, availability="unavailable"),
            host("4", enabled=False, availability="unavailable"),
        ]
        problems = [
            problem("1", severity="warning", host_id="1"),
            problem("2", severity="high", host_id="2"),
        ]
        resources = [
            pressure("1", cpu=70, memory=60, disk=50),
            pressure("2", cpu=40, memory=45, disk=55),
            pressure("3", cpu=90, memory=80, disk=70),
            pressure("4", cpu=99, memory=99, disk=99),
        ]
        trends = [trend("2", metric="cpu", value=60), trend("1", metric="disk", value=75)]
        client = FakeZabbixClient(hosts, problems, resources, trends)
        service = ZabbixDashboardService(client=client)

        response = await service.get_dashboard()

        assert client.trend_calls == [["2", "1", "3"]]
        assert [row.host_id for row in response.top_affected_hosts] == ["2", "1", "3"]
        assert response.top_affected_hosts[0].highest_problem_severity == "high"
        assert response.top_affected_hosts[2].unavailable_interface_count == 1
        assert response.resource_trends == trends
        assert response.summary.hosts_total == 4
        assert response.summary.problems_total == 2
        assert response.summary.resource_hosts_total == 4
        assert response.warnings == []

    asyncio.run(run())


def test_dashboard_service_empty_ranking_still_calls_trends_with_empty_host_ids() -> None:
    async def run() -> None:
        client = FakeZabbixClient([host("1", enabled=True)])
        service = ZabbixDashboardService(client=client)

        response = await service.get_dashboard()

        assert client.trend_calls == [[]]
        assert response.top_affected_hosts == []
        assert response.resource_trends == []
        assert response.warnings == [
            "1 enabled Zabbix host has no current CPU utilization metric.",
            "1 enabled Zabbix host has no current memory utilization metric.",
            "1 enabled Zabbix host has no current disk utilization metric.",
        ]

    asyncio.run(run())


def test_dashboard_service_propagates_trend_client_failure_without_partial_dashboard() -> None:
    async def run() -> None:
        error = IntegrationError(
            source="zabbix",
            code="SOURCE_UNAVAILABLE",
            retryable=True,
        )
        client = FakeZabbixClient(
            [host("1", enabled=True)],
            resource_pressure=[pressure("1", cpu=50)],
            trend_error=error,
        )
        service = ZabbixDashboardService(client=client)

        with pytest.raises(IntegrationError) as exc_info:
            await service.get_dashboard()

        assert exc_info.value is error
        assert client.trend_calls == [["1"]]

    asyncio.run(run())

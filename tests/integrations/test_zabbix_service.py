import asyncio
from datetime import datetime, timezone

from app.integrations.zabbix.models import (
    ZabbixHost,
    ZabbixHostInterface,
    ZabbixProblem,
    ZabbixProblemHost,
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
) -> ZabbixProblem:
    hosts = []
    if mapped:
        hosts = [
            ZabbixProblemHost(
                host_id="10001",
                technical_name="web-01.internal",
                name="Web 01",
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


class FakeZabbixClient:
    def __init__(
        self,
        hosts: list[ZabbixHost],
        active_problems: list[ZabbixProblem] | None = None,
    ) -> None:
        self.hosts = hosts
        self.active_problems = [] if active_problems is None else active_problems
        self.host_calls = 0
        self.problem_calls = 0

    async def list_hosts(self) -> list[ZabbixHost]:
        self.host_calls += 1
        return self.hosts

    async def list_active_problems(self) -> list[ZabbixProblem]:
        self.problem_calls += 1
        return self.active_problems


class CoordinatedClient:
    def __init__(self) -> None:
        self.host_started = asyncio.Event()
        self.problem_started = asyncio.Event()

    async def list_hosts(self) -> list[ZabbixHost]:
        self.host_started.set()
        await asyncio.wait_for(self.problem_started.wait(), timeout=0.2)
        return []

    async def list_active_problems(self) -> list[ZabbixProblem]:
        self.problem_started.set()
        await asyncio.wait_for(self.host_started.wait(), timeout=0.2)
        return []


def test_dashboard_service_fetches_hosts_and_problems_concurrently() -> None:
    async def run() -> None:
        service = ZabbixDashboardService(client=CoordinatedClient())

        response = await service.get_dashboard()

        assert response.summary.hosts_total == 0
        assert response.summary.problems_total == 0
        assert response.active_problems == []

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
        assert response.hosts == []
        assert response.active_problems == []
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

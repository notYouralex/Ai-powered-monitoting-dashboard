from datetime import datetime, timezone

from app.integrations.zabbix.models import (
    ZabbixDiskPressure,
    ZabbixHost,
    ZabbixHostInterface,
    ZabbixProblem,
    ZabbixProblemHost,
    ZabbixResourcePressure,
)
from app.integrations.zabbix.top_hosts import rank_top_affected_hosts


NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def host(
    host_id: str,
    *,
    enabled: bool = True,
    unavailable_interfaces: int = 0,
) -> ZabbixHost:
    interfaces = [
        ZabbixHostInterface(
            interface_id=f"{host_id}-{index}",
            type="agent",
            is_main=index == 0,
            address=f"10.0.0.{index + 1}",
            availability="unavailable",
        )
        for index in range(unavailable_interfaces)
    ]
    return ZabbixHost(
        host_id=host_id,
        technical_name=f"host-{host_id}",
        name=f"Host {host_id}",
        enabled=enabled,
        in_maintenance=False,
        interfaces=interfaces,
    )


def problem(
    event_id: str,
    host_ids: list[str],
    *,
    severity: str = "warning",
) -> ZabbixProblem:
    return ZabbixProblem(
        event_id=event_id,
        trigger_id=f"trigger-{event_id}",
        name=f"Problem {event_id}",
        severity=severity,
        started_at=NOW,
        acknowledged=False,
        suppressed=False,
        hosts=[
            ZabbixProblemHost(
                host_id=host_id,
                technical_name=f"host-{host_id}",
                name=f"Host {host_id}",
            )
            for host_id in host_ids
        ],
    )


def pressure(
    host_id: str,
    *,
    cpu: float | None = None,
    memory: float | None = None,
    disks: list[tuple[str, float]] | None = None,
) -> ZabbixResourcePressure:
    return ZabbixResourcePressure(
        host_id=host_id,
        cpu_used_percent=cpu,
        cpu_observed_at=NOW if cpu is not None else None,
        memory_used_percent=memory,
        memory_observed_at=NOW if memory is not None else None,
        disks=[
            ZabbixDiskPressure(
                filesystem=filesystem,
                used_percent=value,
                observed_at=NOW,
            )
            for filesystem, value in (disks or [])
        ],
    )


def test_ranking_excludes_disabled_hosts_and_hosts_without_candidate_signal() -> None:
    ranked = rank_top_affected_hosts(
        [host("1", enabled=False), host("2"), host("3", unavailable_interfaces=1)],
        [problem("1", ["1"], severity="disaster")],
        [pressure("2")],
    )

    assert [row.host_id for row in ranked] == ["3"]


def test_unknown_problem_severity_ranks_above_disaster() -> None:
    ranked = rank_top_affected_hosts(
        [host("1"), host("2")],
        [
            problem("1", ["1"], severity="disaster"),
            problem("2", ["2"], severity="unknown"),
        ],
        [],
    )

    assert [row.host_id for row in ranked] == ["2", "1"]
    assert ranked[0].highest_problem_severity == "unknown"


def test_unavailable_interfaces_rank_before_problem_count() -> None:
    ranked = rank_top_affected_hosts(
        [host("1", unavailable_interfaces=2), host("2", unavailable_interfaces=1)],
        [
            problem("1", ["1"], severity="high"),
            problem("2", ["2"], severity="high"),
            problem("3", ["2"], severity="high"),
            problem("4", ["2"], severity="high"),
        ],
        [],
    )

    assert [row.host_id for row in ranked] == ["1", "2"]
    assert ranked[0].unavailable_interface_count == 2
    assert ranked[1].active_problem_count == 3


def test_problem_count_ranks_before_peak_resource_utilization() -> None:
    ranked = rank_top_affected_hosts(
        [host("1"), host("2")],
        [
            problem("1", ["1"], severity="warning"),
            problem("2", ["1"], severity="warning"),
            problem("3", ["2"], severity="warning"),
        ],
        [pressure("1", cpu=10), pressure("2", cpu=99)],
    )

    assert [row.host_id for row in ranked] == ["1", "2"]


def test_peak_resource_breaks_remaining_tie_and_exposes_disk_filesystem() -> None:
    ranked = rank_top_affected_hosts(
        [host("1"), host("2")],
        [],
        [
            pressure("1", cpu=70, memory=80, disks=[("/", 90), ("/var", 95)]),
            pressure("2", cpu=94),
        ],
    )

    assert [row.host_id for row in ranked] == ["1", "2"]
    assert ranked[0].peak_resource_percent == 95
    assert ranked[0].peak_resource == "disk"
    assert ranked[0].peak_filesystem == "/var"


def test_equal_peak_prefers_cpu_then_memory_then_lexical_disk() -> None:
    ranked = rank_top_affected_hosts(
        [host("1"), host("2")],
        [],
        [
            pressure("1", cpu=90, memory=90, disks=[("/z", 90), ("/a", 90)]),
            pressure("2", disks=[("/z", 80), ("/a", 80)]),
        ],
    )

    first = next(row for row in ranked if row.host_id == "1")
    second = next(row for row in ranked if row.host_id == "2")
    assert first.peak_resource == "cpu"
    assert first.peak_filesystem is None
    assert second.peak_resource == "disk"
    assert second.peak_filesystem == "/a"


def test_host_id_tie_break_is_numeric_then_lexical_and_result_is_capped_at_10() -> None:
    hosts = [host(str(value)) for value in ["10", "2", "alpha", "beta"]]
    resources = [pressure(row.host_id, cpu=50) for row in hosts]
    for value in range(20, 29):
        hosts.append(host(str(value)))
        resources.append(pressure(str(value), cpu=50))

    ranked = rank_top_affected_hosts(hosts, [], resources)

    assert len(ranked) == 10
    assert [row.host_id for row in ranked[:4]] == ["2", "10", "20", "21"]


def test_no_candidates_returns_empty_list() -> None:
    assert rank_top_affected_hosts([host("1")], [], []) == []

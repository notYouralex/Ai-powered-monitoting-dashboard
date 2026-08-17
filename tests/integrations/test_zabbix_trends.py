from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.zabbix.resource_pressure import select_resource_trend_items
from app.integrations.zabbix.trends import completed_trend_window, normalize_resource_trends


def item(
    item_id: str,
    host_id: str,
    key: str,
    value: str,
    clock: str = "1723521600",
) -> dict[str, str]:
    return {
        "itemid": item_id,
        "hostid": host_id,
        "key_": key,
        "lastvalue": value,
        "lastclock": clock,
    }


def trend(item_id: str, clock: int, value: str) -> dict[str, str]:
    return {"itemid": item_id, "clock": str(clock), "value_avg": value}


def test_selects_one_cpu_memory_and_hottest_disk_per_requested_host() -> None:
    selections = select_resource_trend_items(
        [
            item("10", "2", "system.cpu.util[,idle]", "30", "200"),
            item("2", "2", "system.cpu.util[all,idle,avg1]", "20", "200"),
            item("11", "10", "system.cpu.util[,idle]", "40", "100"),
        ],
        [
            item("20", "2", "vm.memory.size[pavailable]", "10", "500"),
            item("21", "2", "vm.memory.size[pused]", "60", "100"),
            item("22", "10", "vm.memory.size[pavailable]", "25", "100"),
        ],
        [
            item("30", "2", "vfs.fs.size[/,pfree]", "5", "300"),
            item("31", "2", "vfs.fs.size[/,pused]", "80", "100"),
            item("32", "2", "vfs.fs.size[/var,pused]", "90", "100"),
            item("33", "2", "vfs.fs.size[/tmp,pused]", "90", "100"),
            item("34", "10", "vfs.fs.size[/,pfree]", "30", "100"),
        ],
        ["2", "10"],
    )

    assert [
        (row.host_id, row.metric, row.item_id, row.invert, row.filesystem)
        for row in selections
    ] == [
        ("2", "cpu", "2", True, None),
        ("2", "memory", "21", False, None),
        ("2", "disk", "33", False, "/tmp"),
        ("10", "cpu", "11", True, None),
        ("10", "memory", "22", True, None),
        ("10", "disk", "34", True, "/"),
    ]


def test_snmp_direct_utilization_trend_selections_are_not_inverted() -> None:
    selections = select_resource_trend_items(
        [item("1", "2", "system.cpu.util[jnxOperatingCPU.9.1.0.0]", "27")],
        [item("2", "2", "vm.memory.util[memoryUsedPercentage]", "58")],
        [],
        ["2"],
    )

    assert [(row.metric, row.item_id, row.invert) for row in selections] == [
        ("cpu", "1", False),
        ("memory", "2", False),
    ]


def test_selection_ignores_unrequested_hosts_and_preserves_requested_order() -> None:
    selections = select_resource_trend_items(
        [
            item("1", "1", "system.cpu.util[,idle]", "50"),
            item("2", "2", "system.cpu.util[,idle]", "50"),
            item("3", "3", "system.cpu.util[,idle]", "50"),
        ],
        [],
        [],
        ["3", "1"],
    )

    assert [(row.host_id, row.item_id) for row in selections] == [
        ("3", "3"),
        ("1", "1"),
    ]


def test_completed_trend_window_uses_last_24_completed_utc_hours() -> None:
    now = datetime(2026, 8, 13, 8, 44, 37, tzinfo=timezone.utc)

    time_from, time_till = completed_trend_window(now)

    assert datetime.fromtimestamp(time_from, tz=timezone.utc) == datetime(
        2026, 8, 12, 8, 0, tzinfo=timezone.utc
    )
    assert datetime.fromtimestamp(time_till, tz=timezone.utc) == datetime(
        2026, 8, 13, 7, 59, 59, tzinfo=timezone.utc
    )


def test_completed_trend_window_converts_aware_non_utc_input() -> None:
    now = datetime(2026, 8, 13, 16, 44, tzinfo=timezone(timedelta(hours=8)))

    time_from, time_till = completed_trend_window(now)

    assert datetime.fromtimestamp(time_from, tz=timezone.utc) == datetime(
        2026, 8, 12, 8, 0, tzinfo=timezone.utc
    )
    assert datetime.fromtimestamp(time_till, tz=timezone.utc) == datetime(
        2026, 8, 13, 7, 59, 59, tzinfo=timezone.utc
    )


def test_normalizes_inverted_and_direct_trends_with_stable_series_order() -> None:
    selections = select_resource_trend_items(
        [
            item("1", "2", "system.cpu.util[,idle]", "20"),
            item("4", "10", "system.cpu.util[,idle]", "30"),
        ],
        [
            item("2", "2", "vm.memory.size[pavailable]", "25"),
            item("5", "10", "vm.memory.size[pused]", "60"),
        ],
        [
            item("3", "2", "vfs.fs.size[/,pused]", "90"),
            item("6", "10", "vfs.fs.size[/,pfree]", "20"),
        ],
        ["2", "10"],
    )
    start = 1723507200
    end = start + (24 * 3600) - 1

    rows = normalize_resource_trends(
        [
            trend("6", start + 3600, "20"),
            trend("1", start + 3600, "40"),
            trend("1", start, "50"),
            trend("2", start, "25"),
            trend("3", start, "90"),
            trend("5", start, "60"),
        ],
        selections,
        time_from=start,
        time_till=end,
        host_rank=["2", "10"],
    )

    assert [(row.host_id, row.metric, row.filesystem) for row in rows] == [
        ("2", "cpu", None),
        ("2", "memory", None),
        ("2", "disk", "/"),
        ("10", "memory", None),
        ("10", "disk", "/"),
    ]
    assert [point.average_used_percent for point in rows[0].points] == [50.0, 60.0]
    assert rows[1].points[0].average_used_percent == 75.0
    assert rows[2].points[0].average_used_percent == 90.0
    assert rows[3].points[0].average_used_percent == 60.0
    assert rows[4].points[0].average_used_percent == 80.0
    assert [point.observed_at for point in rows[0].points] == sorted(
        point.observed_at for point in rows[0].points
    )


def test_missing_hours_and_items_are_valid_no_data_gaps() -> None:
    selections = select_resource_trend_items(
        [item("1", "2", "system.cpu.util[,idle]", "20")],
        [item("2", "2", "vm.memory.size[pused]", "60")],
        [],
        ["2"],
    )
    start = 1723507200

    rows = normalize_resource_trends(
        [trend("1", start, "50")],
        selections,
        time_from=start,
        time_till=start + (24 * 3600) - 1,
        host_rank=["2"],
    )

    assert len(rows) == 1
    assert rows[0].metric == "cpu"
    assert len(rows[0].points) == 1


@pytest.mark.parametrize(
    "raw_rows",
    [
        [{"itemid": "999", "clock": "1723507200", "value_avg": "50"}],
        [
            trend("1", 1723507200, "50"),
            trend("1", 1723507200, "51"),
        ],
        [trend("1", 1723507201, "50")],
        [trend("1", 1723507200 - 3600, "50")],
        [trend("1", 1723507200, "nan")],
        [trend("1", 1723507200, "101")],
        [{"itemid": "", "clock": "1723507200", "value_avg": "50"}],
    ],
)
def test_malformed_trend_rows_are_rejected(raw_rows: list[dict[str, str]]) -> None:
    selections = select_resource_trend_items(
        [item("1", "2", "system.cpu.util[,idle]", "20")],
        [],
        [],
        ["2"],
    )
    start = 1723507200

    with pytest.raises((TypeError, ValueError, OverflowError, OSError)):
        normalize_resource_trends(
            raw_rows,
            selections,
            time_from=start,
            time_till=start + (24 * 3600) - 1,
            host_rank=["2"],
        )


def test_more_than_24_points_in_one_series_is_rejected() -> None:
    selections = select_resource_trend_items(
        [item("1", "2", "system.cpu.util[,idle]", "20")],
        [],
        [],
        ["2"],
    )
    start = 1723507200
    raw_rows = [trend("1", start + (index * 3600), "50") for index in range(25)]

    with pytest.raises(ValueError, match="24"):
        normalize_resource_trends(
            raw_rows,
            selections,
            time_from=start,
            time_till=start + (25 * 3600) - 1,
            host_rank=["2"],
        )

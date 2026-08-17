import importlib.util
from datetime import datetime, timezone

import pytest

import app.integrations.zabbix.models as zabbix_models
import app.integrations.zabbix.resource_pressure as resource_pressure


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


def test_resource_pressure_models_are_available() -> None:
    assert hasattr(zabbix_models, "ZabbixDiskPressure")
    assert hasattr(zabbix_models, "ZabbixResourcePressure")


def test_resource_pressure_normalizer_module_is_available() -> None:
    assert importlib.util.find_spec("app.integrations.zabbix.resource_pressure") is not None


def test_resource_pressure_normalizer_is_available() -> None:
    assert hasattr(resource_pressure, "normalize_resource_pressure")


def test_normalizer_builds_cpu_memory_and_disk_pressure() -> None:
    rows = resource_pressure.normalize_resource_pressure(
        [item("1", "10001", "system.cpu.util[,idle,avg1]", "25.5")],
        [item("2", "10001", "vm.memory.size[pused]", "61.25")],
        [
            item("3", "10001", "vfs.fs.size[/,pused]", "72.5"),
            item("4", "10001", "vfs.fs.size[/var,pfree]", "20"),
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.host_id == "10001"
    assert row.cpu_used_percent == pytest.approx(74.5)
    assert row.memory_used_percent == pytest.approx(61.25)
    expected_at = datetime.fromtimestamp(1723521600, tz=timezone.utc)
    assert row.cpu_observed_at == expected_at
    assert row.memory_observed_at == expected_at
    assert [(disk.filesystem, disk.used_percent) for disk in row.disks] == [
        ("/", 72.5),
        ("/var", 80.0),
    ]
    assert all(disk.observed_at == expected_at for disk in row.disks)


def test_snmp_direct_cpu_and_memory_utilization_are_normalized_without_inversion() -> None:
    rows = resource_pressure.normalize_resource_pressure(
        [item("1", "7", "system.cpu.util[jnxOperatingCPU.9.1.0.0]", "27")],
        [
            item("2", "7", "vm.memory.util[jnxOperatingBuffer.9.1.0.0]", "39"),
            item("3", "8", "vm.memory.util[memoryUsedPercentage]", "58.75"),
        ],
        [],
    )

    assert [(row.host_id, row.cpu_used_percent, row.memory_used_percent) for row in rows] == [
        ("7", 27.0, 39.0),
        ("8", None, 58.75),
    ]


def test_cpu_uses_aggregate_idle_newest_then_smallest_item_id() -> None:
    rows = resource_pressure.normalize_resource_pressure(
        [
            item("10", "7", "system.cpu.util[all,idle,avg1]", "30", "200"),
            item("2", "7", "system.cpu.util[,idle]", "20", "200"),
            item("1", "7", "system.cpu.util[0,idle,avg1]", "1", "300"),
            item("3", "7", "system.cpu.util[,user,avg1]", "99", "400"),
        ],
        [],
        [],
    )

    assert len(rows) == 1
    assert rows[0].cpu_used_percent == pytest.approx(80.0)
    assert rows[0].cpu_observed_at == datetime.fromtimestamp(200, tz=timezone.utc)


def test_memory_prefers_pused_then_newest_candidate() -> None:
    rows = resource_pressure.normalize_resource_pressure(
        [],
        [
            item("1", "7", "vm.memory.size[pavailable]", "10", "500"),
            item("10", "7", "vm.memory.size[pused]", "50", "100"),
            item("2", "7", "vm.memory.size[pused]", "60", "200"),
        ],
        [],
    )

    assert rows[0].memory_used_percent == pytest.approx(60.0)
    assert rows[0].memory_observed_at == datetime.fromtimestamp(200, tz=timezone.utc)


def test_disk_prefers_pused_unquotes_filesystem_and_sorts_rows() -> None:
    rows = resource_pressure.normalize_resource_pressure(
        [],
        [],
        [
            item("10", "10", "vfs.fs.size[/,pfree]", "15", "300"),
            item("11", "10", "vfs.fs.size[/,pused]", "70", "100"),
            item("12", "10", 'vfs.fs.size["/mnt/data,archive",pused]', "81", "100"),
            item("20", "2", "vfs.fs.size[/,pused]", "50", "100"),
        ],
    )

    assert [row.host_id for row in rows] == ["2", "10"]
    assert [(disk.filesystem, disk.used_percent) for disk in rows[1].disks] == [
        ("/", 70.0),
        ("/mnt/data,archive", 81.0),
    ]


def test_blank_or_zero_clock_current_values_are_skipped() -> None:
    rows = resource_pressure.normalize_resource_pressure(
        [item("1", "7", "system.cpu.util[,idle]", "", "100")],
        [item("2", "7", "vm.memory.size[pused]", "50", "0")],
        [item("3", "7", "vfs.fs.size[/,pused]", "", "0")],
    )

    assert rows == []


@pytest.mark.parametrize(
    ("key", "value", "clock"),
    [
        ("system.cpu.util[,idle]", "nan", "100"),
        ("system.cpu.util[,idle]", "101", "100"),
        ("vm.memory.size[pused]", "-1", "100"),
        ("vm.memory.size[pavailable]", "not-a-number", "100"),
        ("vfs.fs.size[/,pused]", "50", "not-a-clock"),
    ],
)
def test_malformed_recognized_current_value_is_rejected(
    key: str,
    value: str,
    clock: str,
) -> None:
    if key.startswith("system.cpu"):
        args = ([item("1", "7", key, value, clock)], [], [])
    elif key.startswith("vm.memory"):
        args = ([], [item("1", "7", key, value, clock)], [])
    else:
        args = ([], [], [item("1", "7", key, value, clock)])

    with pytest.raises((TypeError, ValueError, OverflowError, OSError)):
        resource_pressure.normalize_resource_pressure(*args)


def test_unsupported_prefix_matches_are_ignored_without_field_validation() -> None:
    rows = resource_pressure.normalize_resource_pressure(
        [{"key_": "system.cpu.utilization.custom", "lastvalue": "garbage"}],
        [{"key_": "vm.memory.size[total]", "lastvalue": "garbage"}],
        [{"key_": "vfs.fs.size[/,total]", "lastvalue": "garbage"}],
    )

    assert rows == []


def test_more_than_64_filesystems_for_one_host_is_rejected() -> None:
    disk_items = [
        item(str(index + 1), "7", f"vfs.fs.size[/fs-{index},pused]", "50")
        for index in range(65)
    ]

    with pytest.raises(ValueError, match="filesystems"):
        resource_pressure.normalize_resource_pressure([], [], disk_items)

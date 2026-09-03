from datetime import datetime, timezone

import pytest

import app.integrations.zabbix.models as zabbix_models
import app.integrations.zabbix.network as network


def item(
    item_id: str,
    host_id: str,
    key: str,
    value: str,
    *,
    units: str,
    clock: str = "1723521600",
) -> dict[str, str]:
    return {
        "itemid": item_id,
        "hostid": host_id,
        "key_": key,
        "lastvalue": value,
        "lastclock": clock,
        "units": units,
    }


def test_network_models_are_available() -> None:
    assert hasattr(zabbix_models, "ZabbixNetworkLivePoint")
    assert hasattr(zabbix_models, "ZabbixNetworkLiveSeries")


def test_normalizer_builds_latency_and_bandwidth_series() -> None:
    rows = network.normalize_network_live(
        [item("1", "7", "icmppingsec", "0.0125", units="s")],
        [item("2", "7", 'net.if.in["eth0",bytes]', "125000", units="bps")],
        [item("3", "7", 'net.if.out["eth0",bytes]', "25000", units="Bps")],
    )

    assert [(row.host_id, row.metric, row.interface) for row in rows] == [
        ("7", "inbound", "eth0"),
        ("7", "latency", None),
        ("7", "outbound", "eth0"),
    ]
    expected_at = datetime.fromtimestamp(1723521600, tz=timezone.utc)
    assert rows[0].points[0].observed_at == expected_at
    assert rows[0].points[0].value == pytest.approx(125000.0)
    assert rows[1].points[0].value == pytest.approx(12.5)
    assert rows[2].points[0].value == pytest.approx(200000.0)


def test_latency_prefers_exact_host_ping_key_then_newest_sample() -> None:
    rows = network.normalize_network_live(
        [
            item("2", "7", "icmppingsec[1.1.1.1]", "0.100", units="s", clock="300"),
            item("10", "7", "icmppingsec", "0.020", units="s", clock="100"),
            item("1", "7", "icmppingsec", "0.030", units="s", clock="200"),
        ],
        [],
        [],
    )

    assert len(rows) == 1
    assert rows[0].metric == "latency"
    assert rows[0].points[0].value == pytest.approx(30.0)
    assert rows[0].points[0].observed_at == datetime.fromtimestamp(200, tz=timezone.utc)


def test_bandwidth_uses_newest_rate_sample_per_host_interface_and_direction() -> None:
    rows = network.normalize_network_live(
        [],
        [
            item("10", "7", "net.if.in[eth0,bytes]", "100", units="bps", clock="100"),
            item("2", "7", "net.if.in[eth0,bytes]", "200", units="bps", clock="200"),
        ],
        [item("3", "7", "net.if.out[eth0,bytes]", "50", units="bps", clock="150")],
    )

    assert [(row.metric, row.points[0].value) for row in rows] == [
        ("inbound", 200.0),
        ("outbound", 50.0),
    ]


def test_non_rate_or_non_byte_interface_items_are_ignored() -> None:
    rows = network.normalize_network_live(
        [],
        [
            item("1", "7", "net.if.in[eth0,bytes]", "123", units="B"),
            item("2", "7", "net.if.in[eth0,packets]", "456", units="pps"),
            {"key_": "net.if.input.custom", "lastvalue": "garbage"},
        ],
        [item("3", "7", "net.if.out[eth0,errors]", "1", units="bps")],
    )

    assert rows == []


@pytest.mark.parametrize(
    ("key", "value", "units", "clock"),
    [
        ("icmppingsec", "-1", "s", "100"),
        ("icmppingsec", "nan", "s", "100"),
        ("net.if.in[eth0,bytes]", "-1", "bps", "100"),
        ("net.if.out[eth0,bytes]", "inf", "bps", "100"),
        ("net.if.in[eth0,bytes]", "1", "bps", "not-a-clock"),
    ],
)
def test_malformed_recognized_network_values_are_rejected(
    key: str,
    value: str,
    units: str,
    clock: str,
) -> None:
    if key.startswith("icmppingsec"):
        args = ([item("1", "7", key, value, units=units, clock=clock)], [], [])
    elif key.startswith("net.if.in"):
        args = ([], [item("1", "7", key, value, units=units, clock=clock)], [])
    else:
        args = ([], [], [item("1", "7", key, value, units=units, clock=clock)])

    with pytest.raises((TypeError, ValueError, OverflowError, OSError)):
        network.normalize_network_live(*args)

from datetime import datetime, timezone

from app.correlation.matcher import match_observations
from app.correlation.models import DeviceObservation
from app.correlation.normalize import normalize_stable_ip


NOW = datetime(2026, 8, 19, 2, 0, tzinfo=timezone.utc)


def observation(source: str, source_record_id: str, **overrides) -> DeviceObservation:
    values = {
        "source": source,
        "source_record_id": source_record_id,
        "observed_at": NOW,
    }
    values.update(overrides)
    return DeviceObservation(**values)


def test_exact_serial_has_priority_over_hostname_difference() -> None:
    left = observation("snipe_it", "101", serial=" SN-001 ", hostname="old-name")
    right = observation("wazuh", "007", serial="sn-001", hostname="new-name")

    match = match_observations(left, right)

    assert match is not None
    assert match.method == "serial"
    assert match.confidence == 100


def test_conflicting_serials_block_automatic_hostname_match() -> None:
    left = observation("snipe_it", "101", serial="SN-001", hostname="server-01")
    right = observation("wazuh", "007", serial="SN-002", hostname="SERVER-01.")

    assert match_observations(left, right) is None


def test_hostname_match_is_case_insensitive_and_ignores_trailing_dot() -> None:
    left = observation("wazuh", "007", hostname="Web-01.Example.COM.")
    right = observation("zabbix", "42", hostname="web-01.example.com")

    match = match_observations(left, right)

    assert match is not None
    assert match.method == "hostname"
    assert match.confidence == 90


def test_stable_ip_matches_only_when_hostnames_do_not_conflict() -> None:
    left = observation("wazuh", "007", stable_ip="10.20.30.40")
    right = observation("zabbix", "42", stable_ip="10.20.30.40")

    match = match_observations(left, right)

    assert match is not None
    assert match.method == "stable_ip"
    assert match.confidence == 80

    conflicting = observation(
        "zabbix",
        "43",
        hostname="different-host",
        stable_ip="10.20.30.40",
    )
    named_left = observation(
        "wazuh",
        "008",
        hostname="server-01",
        stable_ip="10.20.30.40",
    )
    assert match_observations(named_left, conflicting) is None


def test_combined_partial_evidence_requires_name_plus_secondary_evidence() -> None:
    left = observation(
        "snipe_it",
        "101",
        name="Accounting Laptop",
        os="Windows 11",
        location="HQ",
    )
    right = observation(
        "wazuh",
        "007",
        name=" accounting laptop ",
        os="windows 11",
        location="hq",
    )

    match = match_observations(left, right)

    assert match is not None
    assert match.method == "combined"
    assert match.confidence == 70

    weak_left = observation("snipe_it", "102", os="Windows 11", location="HQ")
    weak_right = observation("wazuh", "008", os="windows 11", location="hq")
    assert match_observations(weak_left, weak_right) is None


def test_same_source_records_are_not_automatically_correlated() -> None:
    left = observation("wazuh", "007", hostname="server-01")
    right = observation("wazuh", "008", hostname="server-01")

    assert match_observations(left, right) is None


def test_stable_ip_normalization_rejects_non_unique_addresses() -> None:
    assert normalize_stable_ip("127.0.0.1") is None
    assert normalize_stable_ip("169.254.1.10") is None
    assert normalize_stable_ip("fe80::1") is None
    assert normalize_stable_ip("10.20.30.40") == "10.20.30.40"
    assert normalize_stable_ip("2001:0db8::1") == "2001:db8::1"

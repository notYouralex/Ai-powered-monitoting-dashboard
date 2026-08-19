from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.correlation.models import DeviceObservation
from app.correlation.service import (
    MAX_CORRELATION_OBSERVATIONS,
    CorrelationCapacityError,
    DeviceCorrelationService,
)
from app.db.base import Base
from app.db.models import Device, DeviceSourceLink
from app.db.session import create_engine_for_url


NOW = datetime(2026, 8, 19, 2, 0, tzinfo=timezone.utc)


def make_db() -> Session:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def observation(source: str, source_record_id: str, **overrides) -> DeviceObservation:
    values = {
        "source": source,
        "source_record_id": source_record_id,
        "observed_at": NOW,
    }
    values.update(overrides)
    return DeviceObservation(**values)


def test_service_correlates_two_sources_into_one_device() -> None:
    db = make_db()
    service = DeviceCorrelationService(db)

    decisions = service.correlate(
        [
            observation(
                "wazuh",
                "007",
                name="Server 01",
                hostname="server-01.example.com",
                stable_ip="10.20.30.40",
                os="Ubuntu 26.04",
            ),
            observation(
                "zabbix",
                "42",
                name="SERVER 01",
                hostname="SERVER-01.EXAMPLE.COM.",
                stable_ip="10.20.30.40",
            ),
        ]
    )

    assert [decision.method for decision in decisions] == ["new_device", "hostname"]
    assert decisions[1].confidence == 90
    assert decisions[0].device_id == decisions[1].device_id
    assert db.scalar(select(func.count()).select_from(Device)) == 1
    assert db.scalar(select(func.count()).select_from(DeviceSourceLink)) == 2

    device = db.scalar(select(Device))
    assert device is not None
    assert device.hostname == "server-01.example.com"
    assert device.ip == "10.20.30.40"
    assert device.correlation_confidence == 90


def test_existing_source_record_updates_without_duplicate_link() -> None:
    db = make_db()
    service = DeviceCorrelationService(db)
    first = observation("wazuh", "007", hostname="server-01", os="Ubuntu 24.04")
    later = observation(
        "wazuh",
        "007",
        hostname="server-01",
        os="Ubuntu 26.04",
        observed_at=NOW + timedelta(minutes=5),
    )

    first_decision = service.correlate([first])[0]
    second_decision = service.correlate([later])[0]

    assert second_decision.device_id == first_decision.device_id
    assert second_decision.method == "existing_link"
    assert db.scalar(select(func.count()).select_from(DeviceSourceLink)) == 1
    link = db.scalar(select(DeviceSourceLink))
    assert link is not None
    assert link.last_seen_at == later.observed_at
    assert link.identifiers["os"] == "ubuntu 26.04"


def test_manual_mapping_overrides_conflicting_identifiers() -> None:
    db = make_db()
    service = DeviceCorrelationService(db)
    existing = service.correlate(
        [observation("wazuh", "007", hostname="server-01", stable_ip="10.20.30.40")]
    )[0]

    manual = observation(
        "snipe_it",
        "101",
        name="Inventory Record",
        hostname="different-host",
        serial="SN-999",
    )
    decision = service.correlate(
        [manual],
        manual_mappings={("snipe_it", "101"): existing.device_id},
    )[0]

    assert decision.device_id == existing.device_id
    assert decision.method == "manual"
    assert decision.confidence == 100
    assert decision.manual_override is True
    assert db.scalar(select(func.count()).select_from(Device)) == 1
    link = db.scalar(
        select(DeviceSourceLink).where(
            DeviceSourceLink.source == "snipe_it",
            DeviceSourceLink.source_record_id == "101",
        )
    )
    assert link is not None
    assert link.manual_override is True
    assert link.match_method == "manual"


def test_ambiguous_equal_candidates_are_not_merged() -> None:
    db = make_db()
    service = DeviceCorrelationService(db)

    service.correlate(
        [
            observation("wazuh", "007", hostname="shared-host"),
            observation("wazuh", "008", hostname="shared-host"),
        ]
    )
    decision = service.correlate(
        [observation("zabbix", "42", hostname="shared-host")]
    )[0]

    assert decision.method == "new_device"
    assert db.scalar(select(func.count()).select_from(Device)) == 3


def test_correlation_batch_is_bounded() -> None:
    db = make_db()
    service = DeviceCorrelationService(db)
    observations = [
        observation("wazuh", str(index), hostname=f"host-{index}")
        for index in range(MAX_CORRELATION_OBSERVATIONS + 1)
    ]

    with pytest.raises(CorrelationCapacityError):
        service.correlate(observations)

    assert db.scalar(select(func.count()).select_from(Device)) == 0


def test_existing_link_identifier_update_is_reindexed_within_batch() -> None:
    db = make_db()
    service = DeviceCorrelationService(db)
    service.correlate([observation("wazuh", "007", hostname="old-host")])

    decisions = service.correlate(
        [
            observation(
                "wazuh",
                "007",
                hostname="new-host",
                observed_at=NOW + timedelta(minutes=5),
            ),
            observation("zabbix", "42", hostname="NEW-HOST."),
        ]
    )

    assert decisions[1].method == "hostname"
    assert decisions[0].device_id == decisions[1].device_id
    assert db.scalar(select(func.count()).select_from(Device)) == 1


def test_device_level_serial_conflict_blocks_match_through_other_link() -> None:
    db = make_db()
    service = DeviceCorrelationService(db)
    existing = service.correlate(
        [observation("wazuh", "007", hostname="shared-host")]
    )[0]
    service.correlate(
        [observation("snipe_it", "101", serial="SN-A")],
        manual_mappings={("snipe_it", "101"): existing.device_id},
    )

    decision = service.correlate(
        [observation("zabbix", "42", hostname="shared-host", serial="SN-B")]
    )[0]

    assert decision.method == "new_device"
    assert decision.device_id != existing.device_id
    assert db.scalar(select(func.count()).select_from(Device)) == 2


def test_manual_mapping_can_reassign_existing_source_link() -> None:
    db = make_db()
    service = DeviceCorrelationService(db)
    first, second = service.correlate(
        [
            observation("wazuh", "007", hostname="server-a"),
            observation("wazuh", "008", hostname="server-b"),
        ]
    )
    service.correlate(
        [observation("snipe_it", "101", serial="SN-101")],
        manual_mappings={("snipe_it", "101"): first.device_id},
    )

    decision = service.correlate(
        [observation("snipe_it", "101", serial="SN-101")],
        manual_mappings={("snipe_it", "101"): second.device_id},
    )[0]

    assert decision.method == "manual"
    assert decision.device_id == second.device_id
    link = db.scalar(
        select(DeviceSourceLink).where(
            DeviceSourceLink.source == "snipe_it",
            DeviceSourceLink.source_record_id == "101",
        )
    )
    assert link is not None
    assert link.device_id == second.device_id
    assert link.manual_override is True
    assert db.scalar(select(func.count()).select_from(DeviceSourceLink)) == 3

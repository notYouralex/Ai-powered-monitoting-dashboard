from datetime import datetime, timezone

from app.ai.devices import AIDeviceRepository
from app.db.models import Device, DeviceSourceLink


NOW = datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc)


def test_device_repository_matches_bounded_identity_and_exposes_only_safe_link_metadata(auth_env) -> None:
    with auth_env.session_factory() as db:
        device = Device(
            canonical_name="Server 01",
            hostname="server-01.example.com",
            ip="10.20.30.40",
            serial="SECRET-SERIAL-01",
            asset_tag="AT-001",
            correlation_confidence=92,
        )
        db.add(device)
        db.flush()
        db.add_all(
            [
                DeviceSourceLink(
                    device_id=device.id,
                    source="wazuh",
                    source_record_id="007",
                    identifiers={"hostname": "server-01.example.com"},
                    match_method="hostname",
                    confidence=90,
                    last_seen_at=NOW,
                ),
                DeviceSourceLink(
                    device_id=device.id,
                    source="zabbix",
                    source_record_id="42",
                    identifiers={"hostname": "server-01.example.com"},
                    match_method="hostname",
                    confidence=90,
                    last_seen_at=NOW,
                ),
            ]
        )
        db.commit()

    with auth_env.session_factory() as db:
        repository = AIDeviceRepository(db)
        by_name = repository.find_matches("Explain Server 01", limit=3)
        by_host = repository.find_matches("What is wrong with server-01.example.com?", limit=3)
        by_asset = repository.find_matches("Check AT-001", limit=3)

    assert len(by_name) == 1
    assert by_host[0].device_id == by_name[0].device_id
    assert by_asset[0].device_id == by_name[0].device_id
    assert by_name[0].canonical_name == "Server 01"
    assert by_name[0].hostname == "server-01.example.com"
    assert by_name[0].asset_tag == "AT-001"
    assert by_name[0].linked_sources == ["wazuh", "zabbix"]
    serialized = by_name[0].model_dump_json()
    assert "SECRET-SERIAL-01" not in serialized
    assert "10.20.30.40" not in serialized
    assert "007" not in serialized
    assert "42" not in serialized

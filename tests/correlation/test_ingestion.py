from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.correlation.ingestion import (
    correlate_snipe_it_assets,
    correlate_wazuh_agents,
    correlate_zabbix_hosts,
)
from app.db.base import Base
from app.db.models import Asset, Device, DeviceSourceLink
from app.db.session import create_engine_for_url
from app.integrations.wazuh.models import WazuhAgent
from app.integrations.zabbix.models import ZabbixHost, ZabbixHostInterface


NOW = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)


def make_db() -> Session:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_wazuh_and_zabbix_observations_merge_on_normalized_hostname() -> None:
    db = make_db()
    wazuh = WazuhAgent(
        agent_id="007",
        name="SERVER-01.example.com",
        ip="10.20.30.40",
        status="active",
        os_name="Ubuntu",
        os_version="26.04",
    )
    zabbix = ZabbixHost(
        host_id="42",
        technical_name="server-01.example.com.",
        name="Server 01",
        enabled=True,
        in_maintenance=False,
        interfaces=[
            ZabbixHostInterface(
                interface_id="8",
                type="agent",
                is_main=True,
                address="10.20.30.40",
                availability="available",
            )
        ],
    )

    assert correlate_wazuh_agents(db, [wazuh], observed_at=NOW) == 1
    assert correlate_zabbix_hosts(db, [zabbix], observed_at=NOW) == 1

    devices = list(db.scalars(select(Device)))
    links = list(db.scalars(select(DeviceSourceLink).order_by(DeviceSourceLink.source)))
    assert len(devices) == 1
    assert len(links) == 2
    assert {link.source for link in links} == {"wazuh", "zabbix"}
    assert {link.device_id for link in links} == {devices[0].id}
    assert devices[0].correlation_confidence == 90


def test_snipe_it_ingestion_preserves_strong_asset_identifiers_without_guessing_hostname() -> None:
    db = make_db()
    db.add(
        Asset(
            source_asset_id=101,
            asset_tag="ASSET-101",
            name="Finance Workstation",
            serial="SN-101",
            category="Laptop",
            location="Main Office",
            synced_at=NOW,
        )
    )
    db.commit()

    assert correlate_snipe_it_assets(db) == 1

    link = db.scalar(select(DeviceSourceLink).where(DeviceSourceLink.source == "snipe_it"))
    assert link is not None
    assert link.source_record_id == "101"
    assert link.identifiers["asset_tag"] == "asset-101"
    assert link.identifiers["serial"] == "sn-101"
    assert link.identifiers["name"] == "finance workstation"
    assert "hostname" not in link.identifiers
    assert link.identifiers["device_type"] == "laptop"
    assert link.identifiers["location"] == "main office"


def test_zabbix_ingestion_uses_a_stable_main_interface_ip_only() -> None:
    db = make_db()
    host = ZabbixHost(
        host_id="42",
        technical_name="server-01",
        name="Server 01",
        enabled=True,
        in_maintenance=False,
        interfaces=[
            ZabbixHostInterface(
                interface_id="1",
                type="agent",
                is_main=True,
                address="server-01.example.com",
                availability="available",
            ),
            ZabbixHostInterface(
                interface_id="2",
                type="snmp",
                is_main=False,
                address="10.20.30.40",
                availability="available",
            ),
        ],
    )

    assert correlate_zabbix_hosts(db, [host], observed_at=NOW) == 1

    link = db.scalar(select(DeviceSourceLink).where(DeviceSourceLink.source == "zabbix"))
    assert link is not None
    assert link.identifiers["hostname"] == "server-01"
    assert link.identifiers["stable_ip"] == "10.20.30.40"

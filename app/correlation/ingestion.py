from collections.abc import Sequence
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.correlation.models import DeviceObservation
from app.correlation.normalize import normalize_stable_ip
from app.correlation.service import MAX_CORRELATION_OBSERVATIONS, DeviceCorrelationService
from app.db.models import Asset, ZabbixDashboardCache
from app.integrations.wazuh.models import WazuhAgent
from app.integrations.zabbix.cache import ZABBIX_CACHE_ROW_ID
from app.integrations.zabbix.models import ZabbixDashboardResponse, ZabbixHost


def correlate_wazuh_agents(
    db: Session,
    agents: Sequence[WazuhAgent],
    *,
    observed_at: datetime,
) -> int:
    observations = [
        DeviceObservation(
            source="wazuh",
            source_record_id=agent.agent_id,
            observed_at=observed_at,
            name=agent.name,
            hostname=agent.name,
            stable_ip=agent.ip,
            os=_wazuh_os(agent),
        )
        for agent in agents
    ]
    return _correlate_in_batches(db, observations)


def correlate_zabbix_hosts(
    db: Session,
    hosts: Sequence[ZabbixHost],
    *,
    observed_at: datetime,
) -> int:
    observations = [
        DeviceObservation(
            source="zabbix",
            source_record_id=host.host_id,
            observed_at=observed_at,
            name=host.name,
            hostname=host.technical_name,
            stable_ip=_stable_zabbix_ip(host),
        )
        for host in hosts
    ]
    return _correlate_in_batches(db, observations)


def correlate_zabbix_cache(db: Session) -> int:
    cached = db.get(ZabbixDashboardCache, ZABBIX_CACHE_ROW_ID)
    if cached is None:
        return 0
    try:
        dashboard = ZabbixDashboardResponse.model_validate(cached.snapshot)
    except ValidationError as exc:
        raise ValueError("cached Zabbix dashboard is invalid for device correlation") from exc
    return correlate_zabbix_hosts(
        db,
        dashboard.hosts,
        observed_at=dashboard.observed_at,
    )


def correlate_snipe_it_assets(db: Session) -> int:
    service = DeviceCorrelationService(db)
    correlated = 0
    last_id = 0

    while True:
        assets = list(
            db.scalars(
                select(Asset)
                .where(Asset.id > last_id)
                .order_by(Asset.id)
                .limit(MAX_CORRELATION_OBSERVATIONS)
            )
        )
        if not assets:
            return correlated

        observations = [_snipe_it_observation(asset) for asset in assets]
        service.correlate(observations)
        correlated += len(observations)
        last_id = assets[-1].id


def _correlate_in_batches(db: Session, observations: Sequence[DeviceObservation]) -> int:
    service = DeviceCorrelationService(db)
    correlated = 0
    for start in range(0, len(observations), MAX_CORRELATION_OBSERVATIONS):
        batch = observations[start : start + MAX_CORRELATION_OBSERVATIONS]
        service.correlate(batch)
        correlated += len(batch)
    return correlated


def _snipe_it_observation(asset: Asset) -> DeviceObservation:
    return DeviceObservation(
        source="snipe_it",
        source_record_id=str(asset.source_asset_id),
        observed_at=asset.synced_at,
        name=asset.name,
        serial=asset.serial,
        asset_tag=asset.asset_tag,
        device_type=asset.category,
        location=asset.location,
    )


def _stable_zabbix_ip(host: ZabbixHost) -> str | None:
    interfaces = sorted(host.interfaces, key=lambda interface: not interface.is_main)
    for interface in interfaces:
        if normalize_stable_ip(interface.address) is not None:
            return interface.address
    return None


def _wazuh_os(agent: WazuhAgent) -> str | None:
    parts = [value for value in (agent.os_name, agent.os_version) if value]
    return " ".join(parts) or None

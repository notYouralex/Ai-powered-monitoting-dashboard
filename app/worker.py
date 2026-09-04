import asyncio
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.correlation.ingestion import (
    correlate_snipe_it_assets,
    correlate_wazuh_agents,
    correlate_zabbix_cache,
)
from app.correlation.service import CorrelationCapacityError
from app.core.config import Settings, get_settings
from app.core.errors import IntegrationError
from app.db.session import SessionLocal
from app.integrations.freshservice.client import FreshserviceClient
from app.integrations.freshservice.sync import FreshserviceSyncService
from app.integrations.snipe_it.client import SnipeItClient
from app.integrations.snipe_it.sync import SnipeItSyncService
from app.integrations.zabbix.cache import (
    ZABBIX_CACHE_REFRESH_INTERVAL_SECONDS,
    ZabbixCacheRefreshService,
)
from app.integrations.wazuh.client import WazuhClient
from app.integrations.zabbix.client import ZabbixClient


WAZUH_CORRELATION_INTERVAL_SECONDS = 300


async def run_freshservice_sync_once(
    *,
    settings: Settings,
    session_factory=SessionLocal,
    client_factory: Callable[[Settings], FreshserviceClient] = FreshserviceClient.from_settings,
) -> str:
    if settings.integration_config_state("freshservice") != "configured":
        return "not_configured"

    client = client_factory(settings)
    with session_factory() as db:
        run = await FreshserviceSyncService(client).sync(db)
    return run.status


async def run_snipe_it_sync_once(
    *,
    settings: Settings,
    session_factory=SessionLocal,
    client_factory: Callable[[Settings], SnipeItClient] = SnipeItClient.from_settings,
) -> str:
    if settings.integration_config_state("snipe_it") != "configured":
        return "not_configured"

    client = client_factory(settings)
    with session_factory() as db:
        run = await SnipeItSyncService(client).sync(db)
        if run.status == "success":
            correlate_snipe_it_assets(db)
    return run.status


async def run_zabbix_refresh_once(
    *,
    settings: Settings,
    session_factory=SessionLocal,
    client_factory: Callable[[Settings], ZabbixClient] = ZabbixClient.from_settings,
) -> str:
    if settings.integration_config_state("zabbix") != "configured":
        return "not_configured"

    client = client_factory(settings)
    with session_factory() as db:
        run = await ZabbixCacheRefreshService(client).refresh(db)
        if run.status == "success":
            correlate_zabbix_cache(db)
    return run.status


async def run_wazuh_correlation_once(
    *,
    settings: Settings,
    session_factory=SessionLocal,
    client_factory: Callable[[Settings], WazuhClient] = WazuhClient.from_settings,
) -> str:
    if settings.wazuh_server_config_state() != "configured":
        return "not_configured"

    client = client_factory(settings)
    agents = await client.list_agents()
    observed_at = datetime.now(timezone.utc)
    with session_factory() as db:
        correlate_wazuh_agents(db, agents, observed_at=observed_at)
    return "success"


async def _run_freshservice_loop(settings: Settings) -> None:
    while True:
        try:
            await run_freshservice_sync_once(settings=settings)
        except IntegrationError as exc:
            print(f"Freshservice synchronization failed: {exc.code}", file=sys.stderr)
        except SQLAlchemyError:
            print("Freshservice synchronization database operation failed.", file=sys.stderr)
        await asyncio.sleep(settings.freshservice_sync_interval_seconds)


async def _run_snipe_it_loop(settings: Settings) -> None:
    while True:
        try:
            await run_snipe_it_sync_once(settings=settings)
        except IntegrationError as exc:
            print(f"Snipe-IT synchronization failed: {exc.code}", file=sys.stderr)
        except SQLAlchemyError:
            print("Snipe-IT synchronization database operation failed.", file=sys.stderr)
        except CorrelationCapacityError:
            print("Snipe-IT device correlation capacity exceeded.", file=sys.stderr)
        await asyncio.sleep(settings.snipe_it_sync_interval_seconds)


async def _run_zabbix_loop(settings: Settings) -> None:
    while True:
        try:
            await run_zabbix_refresh_once(settings=settings)
        except IntegrationError as exc:
            print(f"Zabbix refresh failed: {exc.code}", file=sys.stderr)
        except SQLAlchemyError:
            print("Zabbix refresh database operation failed.", file=sys.stderr)
        except (CorrelationCapacityError, ValueError):
            print("Zabbix device correlation failed.", file=sys.stderr)
        await asyncio.sleep(ZABBIX_CACHE_REFRESH_INTERVAL_SECONDS)


async def _run_wazuh_correlation_loop(settings: Settings) -> None:
    while True:
        try:
            await run_wazuh_correlation_once(settings=settings)
        except IntegrationError as exc:
            print(f"Wazuh device correlation failed: {exc.code}", file=sys.stderr)
        except SQLAlchemyError:
            print("Wazuh device correlation database operation failed.", file=sys.stderr)
        except CorrelationCapacityError:
            print("Wazuh device correlation capacity exceeded.", file=sys.stderr)
        await asyncio.sleep(WAZUH_CORRELATION_INTERVAL_SECONDS)


async def run_worker() -> None:
    settings = get_settings()
    await asyncio.gather(
        _run_freshservice_loop(settings),
        _run_snipe_it_loop(settings),
        _run_zabbix_loop(settings),
        _run_wazuh_correlation_loop(settings),
    )


def main() -> int:
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

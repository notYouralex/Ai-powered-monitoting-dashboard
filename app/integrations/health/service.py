from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.contracts import (
    ExecutiveSourceSummary,
    IntegrationHealthSummary,
    IntegrationSource,
    IntegrationStatus,
)
from app.core.errors import IntegrationError
from app.integrations.health.models import IntegrationHealthResponse


INTEGRATION_HEALTH_WAZUH_RANGE = timedelta(hours=24)

_SOURCE_NAMES: dict[IntegrationSource, str] = {
    "wazuh": "Wazuh",
    "zabbix": "Zabbix",
    "snipe_it": "Snipe-IT",
    "freshservice": "Freshservice",
}


class WazuhHealthProvider(Protocol):
    async def get_executive_summary(
        self,
        start: datetime,
        end: datetime,
    ) -> ExecutiveSourceSummary: ...


class SyncHealthProvider(Protocol):
    def get_executive_summary(self) -> ExecutiveSourceSummary: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationHealthService:
    """Aggregate source-owned normalized health without parsing raw source responses."""

    def __init__(
        self,
        *,
        wazuh_service: WazuhHealthProvider,
        zabbix_service: SyncHealthProvider,
        snipe_it_service: SyncHealthProvider,
        freshservice_service: SyncHealthProvider,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._wazuh_service = wazuh_service
        self._zabbix_service = zabbix_service
        self._snipe_it_service = snipe_it_service
        self._freshservice_service = freshservice_service
        self._clock = clock

    async def get_health(self) -> IntegrationHealthResponse:
        observed_at = self._clock()
        wazuh_start = observed_at - INTEGRATION_HEALTH_WAZUH_RANGE
        integrations = [
            await self._get_wazuh_health(wazuh_start, observed_at),
            self._get_sync_health("zabbix", self._zabbix_service, observed_at),
            self._get_sync_health("snipe_it", self._snipe_it_service, observed_at),
            self._get_sync_health("freshservice", self._freshservice_service, observed_at),
        ]
        return IntegrationHealthResponse(
            observed_at=observed_at,
            integrations=integrations,
        )

    async def _get_wazuh_health(
        self,
        start: datetime,
        end: datetime,
    ) -> IntegrationHealthSummary:
        try:
            summary = await self._wazuh_service.get_executive_summary(start, end)
        except IntegrationError as exc:
            return _fallback_health("wazuh", exc, end)
        return summary.health

    def _get_sync_health(
        self,
        source: IntegrationSource,
        service: SyncHealthProvider,
        observed_at: datetime,
    ) -> IntegrationHealthSummary:
        try:
            summary = service.get_executive_summary()
        except IntegrationError as exc:
            return _fallback_health(source, exc, observed_at)
        except SQLAlchemyError:
            return _unavailable_health(source, observed_at)
        return summary.health


def _fallback_health(
    source: IntegrationSource,
    error: IntegrationError,
    observed_at: datetime,
) -> IntegrationHealthSummary:
    if error.code == "SOURCE_NOT_CONFIGURED":
        return _health_summary(
            source=source,
            status="not_configured",
            observed_at=observed_at,
            warning=f"{_SOURCE_NAMES[source]} is not configured.",
        )
    return _unavailable_health(source, observed_at)


def _unavailable_health(
    source: IntegrationSource,
    observed_at: datetime,
) -> IntegrationHealthSummary:
    return _health_summary(
        source=source,
        status="unavailable",
        observed_at=observed_at,
        warning=f"{_SOURCE_NAMES[source]} health is unavailable.",
    )


def _health_summary(
    *,
    source: IntegrationSource,
    status: IntegrationStatus,
    observed_at: datetime,
    warning: str,
) -> IntegrationHealthSummary:
    return IntegrationHealthSummary(
        source=source,
        status=status,
        observed_at=observed_at,
        is_stale=False,
        warnings=[warning],
    )

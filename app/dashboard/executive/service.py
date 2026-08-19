from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary, IntegrationSource
from app.core.errors import IntegrationError
from app.dashboard.executive.models import (
    ExecutiveAttentionItem,
    ExecutiveDashboardResponse,
    ExecutiveDashboardSummary,
    ExecutiveNamedCount,
)


_SOURCE_NAMES: dict[IntegrationSource, str] = {
    "wazuh": "Wazuh",
    "zabbix": "Zabbix",
    "snipe_it": "Snipe-IT",
    "freshservice": "Freshservice",
}


class WazuhExecutiveProvider(Protocol):
    async def get_executive_summary(
        self,
        start: datetime,
        end: datetime,
    ) -> ExecutiveSourceSummary: ...


class SyncExecutiveProvider(Protocol):
    def get_executive_summary(self) -> ExecutiveSourceSummary: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _metric(summary: ExecutiveSourceSummary, key: str) -> int:
    value = summary.metrics.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


class ExecutiveDashboardService:
    """Aggregate source-owned normalized summaries without interpreting raw source data."""

    def __init__(
        self,
        *,
        wazuh_service: WazuhExecutiveProvider,
        zabbix_service: SyncExecutiveProvider,
        snipe_it_service: SyncExecutiveProvider,
        freshservice_service: SyncExecutiveProvider,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._wazuh_service = wazuh_service
        self._zabbix_service = zabbix_service
        self._snipe_it_service = snipe_it_service
        self._freshservice_service = freshservice_service
        self._clock = clock

    async def get_dashboard(
        self,
        start: datetime,
        end: datetime,
    ) -> ExecutiveDashboardResponse:
        observed_at = self._clock()
        sources = [
            await self._get_wazuh_summary(start, end, observed_at),
            self._get_sync_summary("zabbix", self._zabbix_service, observed_at),
            self._get_sync_summary("snipe_it", self._snipe_it_service, observed_at),
            self._get_sync_summary("freshservice", self._freshservice_service, observed_at),
        ]
        wazuh, zabbix, snipe_it, freshservice = sources
        security_alerts = _metric(wazuh, "alerts_high") + _metric(wazuh, "alerts_critical")
        infrastructure_alerts = _metric(zabbix, "problems_high") + _metric(
            zabbix,
            "problems_disaster",
        )
        healthy_sources = sum(source.health.status == "healthy" for source in sources)

        return ExecutiveDashboardResponse(
            observed_at=observed_at,
            range_start=start,
            range_end=end,
            summary=ExecutiveDashboardSummary(
                overall_health_percent=round((healthy_sources / len(sources)) * 100),
                active_alerts=security_alerts + infrastructure_alerts,
                tickets_open=_metric(freshservice, "tickets_open"),
                overdue_open=_metric(freshservice, "overdue_open"),
                assets_total=_metric(snipe_it, "assets_total"),
            ),
            health_distribution=[
                ExecutiveNamedCount(
                    name="Healthy",
                    count=sum(source.health.status == "healthy" for source in sources),
                ),
                ExecutiveNamedCount(
                    name="Degraded",
                    count=sum(source.health.status == "degraded" for source in sources),
                ),
                ExecutiveNamedCount(
                    name="Unavailable",
                    count=sum(source.health.status == "unavailable" for source in sources),
                ),
                ExecutiveNamedCount(
                    name="Not configured",
                    count=sum(source.health.status == "not_configured" for source in sources),
                ),
            ],
            alert_category_distribution=[
                ExecutiveNamedCount(name="Security", count=security_alerts),
                ExecutiveNamedCount(name="Infrastructure", count=infrastructure_alerts),
            ],
            ticket_status_distribution=[
                ExecutiveNamedCount(name="Open", count=_metric(freshservice, "tickets_open")),
                ExecutiveNamedCount(
                    name="Pending",
                    count=_metric(freshservice, "tickets_pending"),
                ),
            ],
            attention_required=[
                ExecutiveAttentionItem(
                    source="Wazuh",
                    issue="Critical Security Alerts",
                    count=_metric(wazuh, "alerts_critical"),
                ),
                ExecutiveAttentionItem(
                    source="Zabbix",
                    issue="Disaster Problems",
                    count=_metric(zabbix, "problems_disaster"),
                ),
                ExecutiveAttentionItem(
                    source="Zabbix",
                    issue="Unavailable Interfaces",
                    count=_metric(zabbix, "interfaces_unavailable"),
                ),
                ExecutiveAttentionItem(
                    source="Freshservice",
                    issue="High-Priority Open Tickets",
                    count=_metric(freshservice, "high_priority_open"),
                ),
                ExecutiveAttentionItem(
                    source="Freshservice",
                    issue="Overdue Tickets",
                    count=_metric(freshservice, "overdue_open"),
                ),
                ExecutiveAttentionItem(
                    source="Snipe-IT",
                    issue="Expired Warranties",
                    count=_metric(snipe_it, "warranty_expired"),
                ),
            ],
            sources=sources,
        )

    async def _get_wazuh_summary(
        self,
        start: datetime,
        end: datetime,
        observed_at: datetime,
    ) -> ExecutiveSourceSummary:
        try:
            return await self._wazuh_service.get_executive_summary(start, end)
        except IntegrationError as exc:
            return _fallback_summary("wazuh", exc, observed_at)

    def _get_sync_summary(
        self,
        source: IntegrationSource,
        service: SyncExecutiveProvider,
        observed_at: datetime,
    ) -> ExecutiveSourceSummary:
        try:
            return service.get_executive_summary()
        except IntegrationError as exc:
            return _fallback_summary(source, exc, observed_at)
        except SQLAlchemyError:
            return _unavailable_summary(source, observed_at)


def _fallback_summary(
    source: IntegrationSource,
    error: IntegrationError,
    observed_at: datetime,
) -> ExecutiveSourceSummary:
    if error.code == "SOURCE_NOT_CONFIGURED":
        warning = f"{_SOURCE_NAMES[source]} is not configured."
        status = "not_configured"
    else:
        warning = f"{_SOURCE_NAMES[source]} Executive summary is unavailable."
        status = "unavailable"

    return _empty_summary(
        source=source,
        status=status,
        observed_at=observed_at,
        warning=warning,
    )


def _unavailable_summary(
    source: IntegrationSource,
    observed_at: datetime,
) -> ExecutiveSourceSummary:
    return _empty_summary(
        source=source,
        status="unavailable",
        observed_at=observed_at,
        warning=f"{_SOURCE_NAMES[source]} Executive summary is unavailable.",
    )


def _empty_summary(
    *,
    source: IntegrationSource,
    status: str,
    observed_at: datetime,
    warning: str,
) -> ExecutiveSourceSummary:
    health = IntegrationHealthSummary(
        source=source,
        status=status,
        observed_at=observed_at,
        is_stale=False,
        warnings=[warning],
    )
    return ExecutiveSourceSummary(
        source=source,
        observed_at=observed_at,
        is_stale=False,
        health=health,
        metrics={},
        warnings=[warning],
    )

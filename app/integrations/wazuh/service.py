import asyncio
from datetime import datetime, timedelta, timezone
from time import perf_counter

from app.contracts import IntegrationHealthSummary
from app.integrations.wazuh.client import WazuhClient
from app.integrations.wazuh.indexer_client import WazuhIndexerClient
from app.integrations.wazuh.models import (
    WazuhAgent,
    WazuhAlertSearchResult,
    WazuhDashboardResponse,
    WazuhDashboardSummary,
)


class WazuhDashboardService:
    """Compose normalized Wazuh server and indexer data for dashboards."""

    def __init__(
        self,
        *,
        agent_client: WazuhClient,
        indexer_client: WazuhIndexerClient,
    ) -> None:
        self._agent_client = agent_client
        self._indexer_client = indexer_client

    async def get_dashboard(
        self,
        start: datetime,
        end: datetime,
    ) -> WazuhDashboardResponse:
        started = perf_counter()
        interval = trend_interval_for_range(end - start)
        agents, alert_result = await asyncio.gather(
            self._agent_client.list_agents(),
            self._indexer_client.search_alerts(
                start,
                end,
                trend_interval=interval,
            ),
        )
        observed_at = datetime.now(timezone.utc)
        response_time_ms = max(0, int((perf_counter() - started) * 1000))

        return WazuhDashboardResponse(
            observed_at=observed_at,
            range_start=start,
            range_end=end,
            health=IntegrationHealthSummary(
                source="wazuh",
                status="healthy",
                observed_at=observed_at,
                last_success_at=observed_at,
                response_time_ms=response_time_ms,
                is_stale=False,
                warnings=[],
            ),
            summary=_build_summary(agents, alert_result),
            agents=agents,
            top_agents=alert_result.top_agents,
            alert_trend=alert_result.trend,
            recent_alerts=alert_result.alerts,
        )


def trend_interval_for_range(duration: timedelta) -> str:
    if duration <= timedelta(hours=6):
        return "15m"
    if duration <= timedelta(hours=48):
        return "1h"
    if duration <= timedelta(days=14):
        return "6h"
    return "1d"


def _build_summary(
    agents: list[WazuhAgent],
    alerts: WazuhAlertSearchResult,
) -> WazuhDashboardSummary:
    agent_counts = {
        "active": 0,
        "disconnected": 0,
        "pending": 0,
        "never_connected": 0,
        "unknown": 0,
    }
    for agent in agents:
        agent_counts[agent.status] += 1

    low = medium = high = critical = 0
    for level, count in alerts.severity_levels.items():
        if level <= 6:
            low += count
        elif level <= 11:
            medium += count
        elif level <= 14:
            high += count
        else:
            critical += count

    return WazuhDashboardSummary(
        agents_total=len(agents),
        agents_active=agent_counts["active"],
        agents_disconnected=agent_counts["disconnected"],
        agents_pending=agent_counts["pending"],
        agents_never_connected=agent_counts["never_connected"],
        agents_unknown=agent_counts["unknown"],
        alerts_total=alerts.total_alerts,
        alerts_low=low,
        alerts_medium=medium,
        alerts_high=high,
        alerts_critical=critical,
    )

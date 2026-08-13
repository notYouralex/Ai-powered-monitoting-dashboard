import asyncio
from datetime import datetime, timedelta, timezone
from app.integrations.wazuh.models import (
    WazuhAgent,
    WazuhAlert,
    WazuhAlertSearchResult,
    WazuhNamedCount,
    WazuhTrendPoint,
)
from app.integrations.wazuh.service import WazuhDashboardService, trend_interval_for_range


START = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc)


class FakeAgentClient:
    async def list_agents(self) -> list[WazuhAgent]:
        return [
            WazuhAgent(agent_id="001", name="web-01", status="active"),
            WazuhAgent(agent_id="002", name="db-01", status="disconnected"),
            WazuhAgent(agent_id="003", name="new-01", status="pending"),
            WazuhAgent(agent_id="004", name="never-01", status="never_connected"),
            WazuhAgent(agent_id="005", name="future-01", status="unknown"),
        ]


class FakeIndexerClient:
    async def search_alerts(
        self,
        start: datetime,
        end: datetime,
        *,
        trend_interval: str,
    ) -> WazuhAlertSearchResult:
        assert start == START
        assert end == END
        assert trend_interval == "15m"
        return WazuhAlertSearchResult(
            total_alerts=15,
            severity_levels={3: 1, 7: 2, 11: 3, 12: 4, 14: 2, 15: 2, 16: 1},
            top_agents=[WazuhNamedCount(name="web-01", count=8)],
            trend=[WazuhTrendPoint(timestamp=START, count=15)],
            alerts=[
                WazuhAlert(
                    timestamp=END - timedelta(minutes=1),
                    rule_id="5710",
                    rule_level=15,
                    description="Severe authentication activity.",
                    agent_id="001",
                    agent_name="web-01",
                    groups=["sshd"],
                )
            ],
        )


def test_dashboard_service_combines_agents_alerts_and_health() -> None:
    async def run() -> None:
        service = WazuhDashboardService(
            agent_client=FakeAgentClient(),
            indexer_client=FakeIndexerClient(),
        )
        response = await service.get_dashboard(START, END)

        assert response.source == "wazuh"
        assert response.range_start == START
        assert response.range_end == END
        assert response.health.source == "wazuh"
        assert response.health.status == "healthy"
        assert response.health.is_stale is False
        assert response.is_stale is False

        assert response.summary.agents_total == 5
        assert response.summary.agents_active == 1
        assert response.summary.agents_disconnected == 1
        assert response.summary.agents_pending == 1
        assert response.summary.agents_never_connected == 1
        assert response.summary.agents_unknown == 1
        assert response.summary.alerts_total == 15
        assert response.summary.alerts_low == 1
        assert response.summary.alerts_medium == 5
        assert response.summary.alerts_high == 6
        assert response.summary.alerts_critical == 3

        assert response.top_agents[0].name == "web-01"
        assert response.alert_trend[0].count == 15
        assert response.recent_alerts[0].rule_id == "5710"
        assert len(response.agents) == 5

    asyncio.run(run())


def test_dashboard_service_builds_bounded_executive_summary() -> None:
    async def run() -> None:
        service = WazuhDashboardService(
            agent_client=FakeAgentClient(),
            indexer_client=FakeIndexerClient(),
        )
        response = await service.get_executive_summary(START, END)

        assert response.source == "wazuh"
        assert response.health.source == "wazuh"
        assert response.health.status == "healthy"
        assert response.is_stale is False
        assert response.warnings == []
        assert response.metrics == {
            "agents_total": 5,
            "agents_active": 1,
            "agents_disconnected": 1,
            "alerts_total": 15,
            "alerts_high": 6,
            "alerts_critical": 3,
        }

    asyncio.run(run())


def test_trend_interval_is_bounded_by_requested_range() -> None:
    assert trend_interval_for_range(timedelta(hours=2)) == "15m"
    assert trend_interval_for_range(timedelta(hours=24)) == "1h"
    assert trend_interval_for_range(timedelta(days=7)) == "6h"
    assert trend_interval_for_range(timedelta(days=30)) == "1d"

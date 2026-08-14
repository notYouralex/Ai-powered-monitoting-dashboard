import asyncio
from datetime import datetime, timedelta, timezone
from app.integrations.wazuh.models import (
    WazuhAgent,
    WazuhAlert,
    WazuhAlertSearchResult,
    WazuhFimSummary,
    WazuhMitreSummary,
    WazuhNamedCount,
    WazuhTrendPoint,
    WazuhVulnerability,
    WazuhVulnerabilitySummary,
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
            top_alerts=[WazuhNamedCount(name="Severe authentication activity.", count=4)],
            fim=WazuhFimSummary(
                total=4,
                added=2,
                modified=1,
                deleted=1,
                top_agents=[WazuhNamedCount(name="web-01", count=4)],
            ),
            mitre=WazuhMitreSummary(
                total=6,
                tactics=[WazuhNamedCount(name="Credential Access", count=6)],
                techniques=[WazuhNamedCount(name="Password Guessing", count=6)],
                top_agents=[WazuhNamedCount(name="web-01", count=6)],
            ),
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

    async def search_vulnerabilities(self) -> WazuhVulnerabilitySummary:
        return WazuhVulnerabilitySummary(
            total=7,
            unique_cves=5,
            affected_agents=2,
            by_severity=[
                WazuhNamedCount(name="Critical", count=2),
                WazuhNamedCount(name="High", count=3),
                WazuhNamedCount(name="Medium", count=2),
            ],
            top_agents=[WazuhNamedCount(name="web-01", count=5)],
            recent=[
                WazuhVulnerability(
                    vulnerability_id="CVE-2026-0001",
                    severity="Critical",
                    score=9.8,
                    detected_at=END - timedelta(minutes=2),
                    agent_id="001",
                    agent_name="web-01",
                    package_name="openssl",
                    package_version="3.0.1",
                    description="Example OpenSSL vulnerability.",
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
        assert response.summary.vulnerabilities_total == 7
        assert response.summary.vulnerabilities_critical == 2
        assert response.summary.vulnerabilities_high == 3
        assert response.summary.vulnerable_agents == 2
        assert response.summary.fim_events == 4
        assert response.summary.mitre_events == 6

        assert response.top_agents[0].name == "web-01"
        assert response.top_alerts[0].count == 4
        assert response.vulnerabilities.recent[0].vulnerability_id == "CVE-2026-0001"
        assert response.fim.added == 2
        assert response.mitre.tactics[0].name == "Credential Access"
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
            "vulnerabilities_total": 7,
            "vulnerabilities_high": 3,
            "vulnerabilities_critical": 2,
            "vulnerable_agents": 2,
            "fim_events": 4,
            "mitre_events": 6,
        }

    asyncio.run(run())


def test_trend_interval_is_bounded_by_requested_range() -> None:
    assert trend_interval_for_range(timedelta(hours=2)) == "15m"
    assert trend_interval_for_range(timedelta(hours=24)) == "1h"
    assert trend_interval_for_range(timedelta(days=7)) == "6h"
    assert trend_interval_for_range(timedelta(days=30)) == "1d"

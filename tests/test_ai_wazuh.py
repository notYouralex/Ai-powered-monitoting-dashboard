import asyncio
from datetime import datetime, timedelta, timezone

from app.ai.models import (
    AIAnalysis,
    AICorrelatedDeviceEvidence,
    AIInvestigationModelOutput,
)
from app.ai.service import AIService
from app.ai.wazuh import build_wazuh_detail_evidence, should_load_wazuh_details
from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary
from app.core.errors import IntegrationError
from app.dashboard.executive.models import ExecutiveDashboardResponse
from app.integrations.wazuh.models import (
    WazuhAgent,
    WazuhAlert,
    WazuhDashboardResponse,
    WazuhDashboardSummary,
    WazuhMitreSummary,
    WazuhNamedCount,
    WazuhVulnerability,
    WazuhVulnerabilitySummary,
)


NOW = datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc)
START = NOW - timedelta(hours=24)


def wazuh_dashboard() -> WazuhDashboardResponse:
    return WazuhDashboardResponse(
        observed_at=NOW,
        range_start=START,
        range_end=NOW,
        health=IntegrationHealthSummary(
            source="wazuh",
            status="healthy",
            observed_at=NOW,
            last_success_at=NOW,
            is_stale=False,
            warnings=[],
        ),
        summary=WazuhDashboardSummary(
            agents_total=2,
            agents_active=1,
            agents_disconnected=1,
            agents_pending=0,
            agents_never_connected=0,
            agents_unknown=0,
            alerts_total=12,
            alerts_low=1,
            alerts_medium=2,
            alerts_high=5,
            alerts_critical=4,
            vulnerabilities_total=3,
            vulnerabilities_critical=1,
            vulnerabilities_high=1,
            vulnerable_agents=2,
            fim_events=0,
            mitre_events=6,
        ),
        agents=[
            WazuhAgent(
                agent_id="001",
                name="web-01",
                ip="10.20.30.41",
                status="active",
                groups=["linux", "web"],
                last_keep_alive=NOW - timedelta(minutes=1),
                os_name="Ubuntu",
                os_version="24.04",
                os_platform="ubuntu",
                os_arch="x86_64",
            ),
            WazuhAgent(
                agent_id="002",
                name="db-01",
                ip="10.20.30.42",
                status="disconnected",
                groups=["linux", "database"],
                last_keep_alive=NOW - timedelta(minutes=18),
                os_name="Ubuntu",
                os_version="24.04",
                os_platform="ubuntu",
                os_arch="x86_64",
            ),
        ],
        vulnerabilities=WazuhVulnerabilitySummary(
            total=3,
            unique_cves=3,
            affected_agents=2,
            by_severity=[
                WazuhNamedCount(name="Critical", count=1),
                WazuhNamedCount(name="High", count=1),
                WazuhNamedCount(name="Medium", count=1),
            ],
            top_agents=[WazuhNamedCount(name="db-01", count=2)],
            recent=[
                WazuhVulnerability(
                    vulnerability_id="CVE-2026-1001",
                    severity="Critical",
                    score=9.8,
                    detected_at=NOW - timedelta(minutes=5),
                    agent_id="002",
                    agent_name="db-01",
                    package_name="openssl",
                    package_version="3.0.1",
                    description="OpenSSL memory safety vulnerability.",
                ),
                WazuhVulnerability(
                    vulnerability_id="CVE-2026-1002",
                    severity="High",
                    score=8.1,
                    detected_at=NOW - timedelta(minutes=8),
                    agent_id="001",
                    agent_name="web-01",
                    package_name="nginx",
                    package_version="1.24.0",
                    description="Nginx request processing vulnerability.",
                ),
                WazuhVulnerability(
                    vulnerability_id="CVE-2026-1003",
                    severity="Medium",
                    score=5.0,
                    detected_at=NOW - timedelta(minutes=12),
                    agent_id="001",
                    agent_name="web-01",
                    package_name="curl",
                    package_version="8.5.0",
                    description="Curl validation vulnerability.",
                ),
            ],
        ),
        mitre=WazuhMitreSummary(
            total=6,
            tactics=[
                WazuhNamedCount(name="Credential Access", count=4),
                WazuhNamedCount(name="Initial Access", count=2),
            ],
            techniques=[
                WazuhNamedCount(name="Password Guessing", count=4),
                WazuhNamedCount(name="External Remote Services", count=2),
            ],
            top_agents=[WazuhNamedCount(name="web-01", count=4)],
        ),
        recent_alerts=[
            WazuhAlert(
                timestamp=NOW - timedelta(minutes=2),
                rule_id="5710",
                rule_level=15,
                description="Severe authentication activity.",
                agent_id="001",
                agent_name="web-01",
                groups=["sshd", "authentication_failed"],
            ),
            WazuhAlert(
                timestamp=NOW - timedelta(minutes=4),
                rule_id="87101",
                rule_level=13,
                description="Malware-related file activity detected.",
                agent_id="002",
                agent_name="db-01",
                groups=["malware"],
            ),
            WazuhAlert(
                timestamp=NOW - timedelta(minutes=10),
                rule_id="5501",
                rule_level=7,
                description="User authentication warning.",
                agent_id="002",
                agent_name="db-01",
                groups=["authentication"],
            ),
        ],
    )


def executive_summary(source: str, metrics: dict | None = None) -> ExecutiveSourceSummary:
    return ExecutiveSourceSummary(
        source=source,
        observed_at=NOW,
        health=IntegrationHealthSummary(
            source=source,
            status="healthy",
            observed_at=NOW,
            is_stale=False,
            warnings=[],
        ),
        metrics=metrics or {},
        warnings=[],
    )


def executive_dashboard() -> ExecutiveDashboardResponse:
    return ExecutiveDashboardResponse(
        observed_at=NOW,
        range_start=START,
        range_end=NOW,
        sources=[
            executive_summary(
                "wazuh",
                {
                    "agents_disconnected": 1,
                    "alerts_high": 5,
                    "alerts_critical": 4,
                    "vulnerabilities_high": 1,
                    "vulnerabilities_critical": 1,
                    "vulnerable_agents": 2,
                },
            ),
            executive_summary("zabbix"),
            executive_summary("snipe_it"),
            executive_summary("freshservice"),
        ],
    )


def test_wazuh_detail_projects_critical_alert_topics_without_ids_or_ips() -> None:
    detail = build_wazuh_detail_evidence(
        "What are the critical alerts about?",
        wazuh_dashboard(),
    )

    assert detail is not None
    assert detail.recent_alert_matches == 1
    assert len(detail.alerts) == 1
    assert detail.alerts[0].description == "Severe authentication activity."
    assert detail.alerts[0].rule_level == 15
    assert detail.alerts[0].agent_name == "web-01"
    serialized = detail.model_dump_json()
    assert "rule_id" not in serialized
    assert "agent_id" not in serialized
    assert "10.20.30.41" not in serialized
    assert "5710" not in serialized


def test_wazuh_detail_prioritizes_vulnerabilities_and_filters_disconnected_agents() -> None:
    vulnerabilities = build_wazuh_detail_evidence(
        "What critical vulnerabilities should we investigate first?",
        wazuh_dashboard(),
    )
    disconnected = build_wazuh_detail_evidence(
        "Which Wazuh agents are disconnected?",
        wazuh_dashboard(),
    )

    assert vulnerabilities is not None
    assert vulnerabilities.recent_vulnerability_matches == 1
    assert vulnerabilities.vulnerabilities[0].vulnerability_id == "CVE-2026-1001"
    assert vulnerabilities.vulnerabilities[0].severity == "Critical"
    assert vulnerabilities.vulnerabilities[0].package_name == "openssl"
    assert disconnected is not None
    assert disconnected.agent_matches == 1
    assert disconnected.agents[0].name == "db-01"
    assert disconnected.agents[0].status == "disconnected"
    serialized = disconnected.model_dump_json()
    assert "agent_id" not in serialized
    assert "10.20.30.42" not in serialized


def test_wazuh_detail_returns_bounded_mitre_names_and_count_only_stays_aggregate() -> None:
    mitre = build_wazuh_detail_evidence(
        "What MITRE techniques are appearing?",
        wazuh_dashboard(),
    )

    assert mitre is not None
    assert [item.name for item in mitre.mitre_techniques] == [
        "Password Guessing",
        "External Remote Services",
    ]
    assert [item.count for item in mitre.mitre_techniques] == [4, 2]
    assert should_load_wazuh_details("How many critical alerts are there?") is False
    assert build_wazuh_detail_evidence(
        "How many critical alerts are there?",
        wazuh_dashboard(),
    ) is None


def test_wazuh_detail_can_use_agent_id_internally_without_exposing_it() -> None:
    detail = build_wazuh_detail_evidence(
        "Why is this Wazuh agent disconnected?",
        wazuh_dashboard(),
        agent_id="002",
    )

    assert detail is not None
    assert [agent.name for agent in detail.agents] == ["db-01"]
    assert all(alert.agent_name == "db-01" for alert in detail.alerts)
    assert all(item.agent_name == "db-01" for item in detail.vulnerabilities)
    serialized = detail.model_dump_json()
    assert "agent_id" not in serialized
    assert "10.20.30.42" not in serialized


class FakeExecutiveService:
    async def get_dashboard(self, start, end):
        return executive_dashboard()


class RecordingProvider:
    def __init__(self) -> None:
        self.calls = []

    async def generate(self, *, purpose, system_prompt, prompt):
        self.calls.append({"purpose": purpose, "prompt": prompt})
        return AIAnalysis(summary="Unused.", confidence="medium")

    async def generate_investigation(self, *, system_prompt, prompt):
        self.calls.append({"purpose": "investigation", "prompt": prompt})
        return AIInvestigationModelOutput(
            likely_explanation=None,
            confidence="medium",
        )


class EmptyDeviceRepository:
    def find_matches(self, question, *, limit=3):
        return []

    def get_source_record_id(self, device_id, source):
        return None


class WazuhDeviceRepository:
    def find_matches(self, question, *, limit=3):
        return [
            AICorrelatedDeviceEvidence(
                device_id=42,
                canonical_name="db-01",
                hostname="db-01.example.com",
                correlation_confidence=95,
                linked_sources=["wazuh"],
            )
        ]

    def get_source_record_id(self, device_id, source):
        if device_id == 42 and source == "wazuh":
            return "002"
        return None


class FakeWazuhService:
    def __init__(self, *, error: IntegrationError | None = None) -> None:
        self.error = error
        self.calls = []

    async def get_dashboard(self, start, end):
        self.calls.append((start, end))
        if self.error is not None:
            raise self.error
        return wazuh_dashboard()


def test_ai_service_adds_wazuh_detail_for_source_question_but_not_count_only() -> None:
    async def run() -> None:
        provider = RecordingProvider()
        wazuh_service = FakeWazuhService()
        service = AIService(
            provider=provider,
            executive_service=FakeExecutiveService(),
            device_repository=EmptyDeviceRepository(),
            wazuh_service=wazuh_service,
        )

        detail_response = await service.investigate(
            "What are the critical Wazuh alerts about?",
            START,
            NOW,
        )
        assert detail_response.classification.scope == "source"
        assert detail_response.classification.source == "wazuh"
        assert wazuh_service.calls == [(START, NOW)]
        assert any(
            "Severe authentication activity" in fact
            for fact in detail_response.analysis.evidence
        )
        prompt = provider.calls[-1]["prompt"]
        assert "Severe authentication activity" in prompt
        assert '"agent_id"' not in prompt
        assert "10.20.30.41" not in prompt

        wazuh_service.calls.clear()
        count_response = await service.investigate(
            "How many critical Wazuh alerts are there?",
            START,
            NOW,
        )
        assert wazuh_service.calls == []
        assert "Wazuh alerts critical: 4" in count_response.analysis.evidence

    asyncio.run(run())


def test_ai_service_uses_internal_wazuh_agent_link_for_device_detail() -> None:
    async def run() -> None:
        provider = RecordingProvider()
        service = AIService(
            provider=provider,
            executive_service=FakeExecutiveService(),
            device_repository=WazuhDeviceRepository(),
            wazuh_service=FakeWazuhService(),
        )

        response = await service.investigate(
            "Why is db-01 Wazuh agent disconnected?",
            START,
            NOW,
        )

        assert response.classification.scope == "device"
        assert response.classification.source == "wazuh"
        assert any("Wazuh agent db-01: disconnected" in fact for fact in response.analysis.evidence)
        prompt = provider.calls[-1]["prompt"]
        assert '"agent_id"' not in prompt
        assert "10.20.30.42" not in prompt
        assert response.analysis.confidence == "low"

    asyncio.run(run())


def test_ai_service_falls_back_when_wazuh_detail_source_is_unavailable() -> None:
    async def run() -> None:
        service = AIService(
            provider=RecordingProvider(),
            executive_service=FakeExecutiveService(),
            device_repository=EmptyDeviceRepository(),
            wazuh_service=FakeWazuhService(
                error=IntegrationError(
                    source="wazuh",
                    code="SOURCE_UNAVAILABLE",
                    retryable=True,
                )
            ),
        )

        response = await service.investigate(
            "What are the critical Wazuh alerts about?",
            START,
            NOW,
        )

        assert any(
            "wazuh detail evidence is temporarily unavailable" in warning.lower()
            for warning in response.analysis.warnings
        )
        assert "Wazuh alerts critical: 4" in response.analysis.evidence

    asyncio.run(run())

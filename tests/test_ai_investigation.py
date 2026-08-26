import asyncio
from datetime import datetime, timedelta, timezone

from app.ai.evidence import build_investigation_evidence
from app.ai.investigation import build_investigation_prompt, ground_investigation_analysis
from app.ai.models import (
    AIAnalysis,
    AICorrelatedDeviceEvidence,
    AIInvestigationModelOutput,
    AIQuestionClassification,
)
from app.ai.service import AIService
from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary
from app.dashboard.executive.models import ExecutiveDashboardResponse


NOW = datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc)
START = NOW - timedelta(hours=24)


def summary(source, *, metrics=None, status="healthy", stale=False, warnings=None):
    warning_values = warnings or []
    return ExecutiveSourceSummary(
        source=source,
        observed_at=NOW,
        is_stale=stale,
        health=IntegrationHealthSummary(
            source=source,
            status=status,
            observed_at=NOW,
            is_stale=stale,
            warnings=warning_values,
        ),
        metrics=metrics or {},
        warnings=warning_values,
    )


def dashboard() -> ExecutiveDashboardResponse:
    return ExecutiveDashboardResponse(
        observed_at=NOW,
        range_start=START,
        range_end=NOW,
        sources=[
            summary(
                "wazuh",
                metrics={
                    "agents_total": 20,
                    "agents_active": 18,
                    "agents_disconnected": 2,
                    "alerts_high": 3,
                    "alerts_critical": 1,
                },
            ),
            summary(
                "zabbix",
                metrics={"hosts_total": 12, "problems_disaster": 0, "problems_high": 1},
            ),
            summary(
                "snipe_it",
                metrics={"assets_total": 100, "assets_unassigned": 3},
            ),
            summary(
                "freshservice",
                metrics={"tickets_open": 14, "overdue_open": 4},
            ),
        ],
    )


def device() -> AICorrelatedDeviceEvidence:
    return AICorrelatedDeviceEvidence(
        device_id=23,
        canonical_name="PC-023",
        hostname="pc-023.example.com",
        asset_tag="AT-023",
        correlation_confidence=92,
        linked_sources=["wazuh", "snipe_it"],
    )


def test_investigation_prompt_teaches_count_free_category_based_recommendations() -> None:
    evidence = build_investigation_evidence(
        dashboard(),
        AIQuestionClassification(scope="environment"),
        device=None,
    )

    prompt = build_investigation_prompt("What needs attention?", evidence)

    assert "Use metric names and categories to choose investigation topics" in prompt
    assert "omit their values from prose" in prompt
    assert "Review affected Wazuh agents" in prompt
    assert "Review unacknowledged Zabbix problems" in prompt
    assert "Review escalated Freshservice tickets" in prompt
    assert "There are 251 critical vulnerabilities" in prompt
    assert "416 assets are unassigned" in prompt


def test_grounding_keeps_count_free_review_actions_and_rejects_counted_versions() -> None:
    evidence = build_investigation_evidence(
        dashboard(),
        AIQuestionClassification(scope="environment"),
        device=None,
    )
    model_output = AIInvestigationModelOutput(
        likely_explanation=None,
        recommended_investigation=[
            "Review Wazuh critical alerts and disconnected agents.",
            "Review unacknowledged Zabbix problems for operator attention.",
            "Review escalated Freshservice tickets for ownership and current investigation status.",
            "Review 2 disconnected Wazuh agents.",
        ],
        confidence="medium",
    )

    grounded = ground_investigation_analysis(model_output, evidence)

    assert grounded.recommended_investigation == [
        "Review Wazuh critical alerts and disconnected agents.",
        "Review unacknowledged Zabbix problems for operator attention.",
        "Review escalated Freshservice tickets for ownership and current investigation status.",
    ]
    assert any("omitted" in warning.lower() for warning in grounded.warnings)


def test_environment_investigation_evidence_keeps_only_attention_signals_and_affected_sources() -> None:
    evidence = build_investigation_evidence(
        dashboard(),
        AIQuestionClassification(scope="environment"),
        device=None,
    )

    assert [item.source for item in evidence.sources] == [
        "wazuh",
        "zabbix",
        "snipe_it",
        "freshservice",
    ]
    assert evidence.sources[0].metrics == {
        "agents_disconnected": 2,
        "alerts_high": 3,
        "alerts_critical": 1,
    }
    assert evidence.sources[1].metrics == {"problems_high": 1}
    assert evidence.sources[2].metrics == {"assets_unassigned": 3}
    assert evidence.sources[3].metrics == {"tickets_open": 14, "overdue_open": 4}
    serialized = evidence.model_dump_json()
    assert "agents_total" not in serialized
    assert "agents_active" not in serialized
    assert "hosts_total" not in serialized
    assert "assets_total" not in serialized


def test_environment_investigation_evidence_omits_clear_sources_but_keeps_degraded_state() -> None:
    clear_dashboard = ExecutiveDashboardResponse(
        observed_at=NOW,
        range_start=START,
        range_end=NOW,
        sources=[
            summary("wazuh", metrics={"agents_total": 20, "alerts_critical": 0}),
            summary("zabbix", metrics={"hosts_total": 12}, status="degraded"),
            summary("snipe_it", metrics={"assets_total": 100}),
            summary("freshservice", metrics={"tickets_open": 0}),
        ],
    )

    evidence = build_investigation_evidence(
        clear_dashboard,
        AIQuestionClassification(scope="environment"),
        device=None,
    )

    assert [item.source for item in evidence.sources] == ["zabbix"]
    assert evidence.sources[0].status == "degraded"
    assert evidence.sources[0].metrics == {}


def test_investigation_evidence_selects_only_requested_source() -> None:
    evidence = build_investigation_evidence(
        dashboard(),
        AIQuestionClassification(scope="source", source="freshservice"),
        device=None,
    )

    assert [item.source for item in evidence.sources] == ["freshservice"]
    assert evidence.device is None
    assert "raw event" in " ".join(evidence.limitations).lower()


def test_device_investigation_uses_only_linked_sources_and_marks_aggregate_limitation() -> None:
    evidence = build_investigation_evidence(
        dashboard(),
        AIQuestionClassification(
            scope="device",
            device_id=23,
            device_match_count=1,
        ),
        device=device(),
    )

    assert [item.source for item in evidence.sources] == ["wazuh", "snipe_it"]
    assert evidence.device is not None
    assert evidence.device.canonical_name == "PC-023"
    limitations = " ".join(evidence.limitations).lower()
    assert "environment-level" in limitations
    assert "not attributed" in limitations


class FakeExecutiveService:
    async def get_dashboard(self, start, end):
        return dashboard()


class FakeDeviceRepository:
    def __init__(self, matches):
        self.matches = matches

    def find_matches(self, question, *, limit=3):
        return self.matches[:limit]


class BadInvestigationProvider:
    def __init__(self):
        self.calls = []

    async def generate(self, *, purpose, system_prompt, prompt):
        self.calls.append({"purpose": purpose, "system_prompt": system_prompt, "prompt": prompt})
        return AIAnalysis(summary="Unused summary.", confidence="high")

    async def generate_investigation(self, *, system_prompt, prompt):
        self.calls.append({"purpose": "investigation", "system_prompt": system_prompt, "prompt": prompt})
        return AIInvestigationModelOutput(
            likely_explanation="High CPU caused the Wazuh critical alerts.",
            recommended_investigation=[
                "sudo systemctl restart wazuh-manager",
                "Review the Wazuh alert context and authentication history.",
            ],
            confidence="high",
        )


def test_investigation_service_replaces_model_facts_and_filters_unsupported_reasoning() -> None:
    async def run() -> None:
        provider = BadInvestigationProvider()
        service = AIService(
            provider=provider,
            executive_service=FakeExecutiveService(),
            device_repository=FakeDeviceRepository([]),
        )

        response = await service.investigate(
            "What is happening in Wazuh?",
            START,
            NOW,
        )

        assert provider.calls[0]["purpose"] == "investigation"
        assert response.classification.scope == "source"
        assert response.classification.source == "wazuh"
        assert response.analysis.summary.startswith("Selected Wazuh investigation evidence:")
        assert "Wazuh alerts critical: 1" in response.analysis.evidence
        assert response.analysis.likely_explanation is None
        assert response.analysis.contributing_factors == []
        assert response.analysis.operational_impact is None
        assert response.analysis.recommended_investigation == [
            "Review the Wazuh alert context and authentication history."
        ]
        assert response.analysis.confidence == "medium"

    asyncio.run(run())


def test_device_investigation_never_claims_environment_metrics_are_device_events() -> None:
    async def run() -> None:
        provider = BadInvestigationProvider()
        service = AIService(
            provider=provider,
            executive_service=FakeExecutiveService(),
            device_repository=FakeDeviceRepository([device()]),
        )

        response = await service.investigate(
            "Explain Wazuh alerts affecting PC-023",
            START,
            NOW,
        )

        assert response.classification.scope == "device"
        assert response.classification.source == "wazuh"
        assert response.device is not None
        assert response.device.canonical_name == "PC-023"
        assert response.analysis.confidence == "low"
        assert response.analysis.likely_explanation is None
        assert response.analysis.operational_impact is None
        assert "Environment-level Wazuh alerts critical: 1" in response.analysis.evidence
        assert "Wazuh alerts critical: 1" not in response.analysis.evidence
        assert any("not attributed" in warning.lower() for warning in response.analysis.warnings)

    asyncio.run(run())


def test_investigation_source_warnings_are_bounded_to_response_contract() -> None:
    async def run() -> None:
        noisy_dashboard = ExecutiveDashboardResponse(
            observed_at=NOW,
            range_start=START,
            range_end=NOW,
            sources=[
                summary(source_name, warnings=[f"{source_name} warning {index}" for index in range(5)])
                for source_name in ("wazuh", "zabbix", "snipe_it", "freshservice")
            ],
        )

        class NoisyExecutiveService:
            async def get_dashboard(self, start, end):
                return noisy_dashboard

        service = AIService(
            provider=BadInvestigationProvider(),
            executive_service=NoisyExecutiveService(),
            device_repository=FakeDeviceRepository([]),
        )
        response = await service.investigate("What needs attention today?", START, NOW)

        assert len(response.source_warnings) == 12

    asyncio.run(run())


def test_ambiguous_device_question_skips_qwen() -> None:
    async def run() -> None:
        provider = BadInvestigationProvider()
        service = AIService(
            provider=provider,
            executive_service=FakeExecutiveService(),
            device_repository=FakeDeviceRepository(
                [
                    device(),
                    AICorrelatedDeviceEvidence(
                        device_id=24,
                        canonical_name="PC-023",
                        correlation_confidence=80,
                        linked_sources=["zabbix"],
                    ),
                ]
            ),
        )

        response = await service.investigate("Explain PC-023", START, NOW)

        assert provider.calls == []
        assert response.classification.scope == "device"
        assert response.classification.device_id is None
        assert response.classification.device_match_count == 2
        assert response.analysis.confidence == "low"
        assert "ambiguous" in response.analysis.summary.lower()

    asyncio.run(run())

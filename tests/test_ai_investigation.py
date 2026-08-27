import asyncio
from datetime import datetime, timedelta, timezone

from app.ai.evidence import build_investigation_evidence, build_zabbix_host_evidence
from app.ai.investigation import build_investigation_prompt, ground_investigation_analysis
from app.ai.models import (
    AIAnalysis,
    AICorrelatedDeviceEvidence,
    AIFreshserviceTicketEvidence,
    AIFreshserviceTicketSetEvidence,
    AISnipeItAssetEvidence,
    AISnipeItAssetSetEvidence,
    AIInvestigationModelOutput,
    AIQuestionClassification,
)
from app.ai.service import AIService
from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary
from app.dashboard.executive.models import ExecutiveDashboardResponse
from app.integrations.zabbix.models import (
    ZabbixDashboardResponse,
    ZabbixDashboardSummary,
    ZabbixDiskPressure,
    ZabbixHost,
    ZabbixHostInterface,
    ZabbixProblem,
    ZabbixProblemHost,
    ZabbixResourcePressure,
)


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
    limitations = " ".join(evidence.limitations).lower()
    assert "bounded normalized" in limitations
    assert "raw source records" in limitations
    assert "sensitive fields" in limitations


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


def test_out_of_scope_question_skips_dashboard_and_qwen() -> None:
    async def run() -> None:
        provider = BadInvestigationProvider()

        class UnexpectedExecutiveService:
            async def get_dashboard(self, start, end):
                raise AssertionError("out-of-scope questions must not load monitoring evidence")

        service = AIService(
            provider=provider,
            executive_service=UnexpectedExecutiveService(),
            device_repository=FakeDeviceRepository([]),
        )

        response = await service.investigate("What is the capital of France?", START, NOW)

        assert provider.calls == []
        assert response.classification.scope == "environment"
        assert response.classification.source is None
        assert response.analysis.confidence == "high"
        assert response.analysis.evidence == []
        assert response.analysis.recommended_investigation == []
        assert "limited to the monitored environment" in response.analysis.summary.lower()
        assert any("not sent to the ai model" in warning.lower() for warning in response.analysis.warnings)
        assert response.source_warnings == []

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


def zabbix_host_dashboard() -> ZabbixDashboardResponse:
    summary_values = {name: 0 for name in ZabbixDashboardSummary.model_fields}
    return ZabbixDashboardResponse(
        observed_at=NOW,
        health=IntegrationHealthSummary(
            source="zabbix",
            status="healthy",
            observed_at=NOW,
            last_success_at=NOW,
            is_stale=False,
            warnings=[],
        ),
        summary=ZabbixDashboardSummary(**summary_values),
        hosts=[
            ZabbixHost(
                host_id="42",
                technical_name="server-42.example.com",
                name="Server 42",
                enabled=True,
                in_maintenance=False,
                interfaces=[
                    ZabbixHostInterface(
                        interface_id="1",
                        type="agent",
                        is_main=True,
                        availability="unavailable",
                    )
                ],
            )
        ],
        active_problems=[
            ZabbixProblem(
                event_id="100",
                trigger_id="200",
                name="Zabbix agent is not available",
                severity="high",
                started_at=NOW - timedelta(minutes=20),
                acknowledged=False,
                suppressed=False,
                hosts=[
                    ZabbixProblemHost(
                        host_id="42",
                        technical_name="server-42.example.com",
                        name="Server 42",
                    )
                ],
            )
        ],
        resource_pressure=[
            ZabbixResourcePressure(
                host_id="42",
                cpu_used_percent=35.0,
                cpu_observed_at=NOW,
                memory_used_percent=72.0,
                memory_observed_at=NOW,
                disks=[
                    ZabbixDiskPressure(
                        filesystem="/",
                        used_percent=81.0,
                        observed_at=NOW,
                    )
                ],
            )
        ],
    )


def test_source_health_reason_is_grounded_as_application_controlled_explanation() -> None:
    health_dashboard = ExecutiveDashboardResponse(
        observed_at=NOW,
        range_start=START,
        range_end=NOW,
        sources=[
            summary("wazuh"),
            summary("zabbix"),
            summary(
                "snipe_it",
                status="degraded",
                stale=True,
                warnings=[
                    "The latest Snipe-IT synchronization failed; showing last successful data."
                ],
            ),
            summary("freshservice"),
        ],
    )
    evidence = build_investigation_evidence(
        health_dashboard,
        AIQuestionClassification(scope="source", source="snipe_it"),
        device=None,
    )

    assert evidence.sources[0].health_reasons == [
        "The latest Snipe-IT synchronization failed; showing last successful data."
    ]

    grounded = ground_investigation_analysis(
        AIInvestigationModelOutput(
            likely_explanation=None,
            recommended_investigation=[],
            confidence="medium",
        ),
        evidence,
    )

    assert grounded.likely_explanation is not None
    assert "latest snipe-it synchronization failed" in grounded.likely_explanation.lower()
    assert any("Snipe-IT source reason:" in fact for fact in grounded.evidence)


def test_zabbix_host_evidence_is_bounded_and_excludes_interface_addresses() -> None:
    evidence = build_zabbix_host_evidence(zabbix_host_dashboard(), "42")

    assert evidence is not None
    assert evidence.status == "unavailable"
    assert evidence.unavailable_interface_count == 1
    assert evidence.active_problem_count == 1
    assert evidence.problems[0].name == "Zabbix agent is not available"
    assert evidence.problems[0].severity == "high"
    assert evidence.cpu_used_percent == 35.0
    assert evidence.memory_used_percent == 72.0
    assert evidence.peak_disk_used_percent == 81.0
    serialized = evidence.model_dump_json()
    assert "server-42.example.com" not in serialized
    assert "interface_id" not in serialized
    assert "address" not in serialized


class FakeFreshserviceMetricsRepository:
    def __init__(self):
        self.detail_limits = []

    def metrics_for_question(self, question, *, start, end):
        return {"tickets_resolved_in_range": 7}

    def ticket_details_for_question(self, question, *, start, end, limit=20):
        self.detail_limits.append(limit)
        if "about" not in question.casefold():
            return None
        return AIFreshserviceTicketSetEvidence(
            matching_count=2,
            truncated=False,
            tickets=[
                AIFreshserviceTicketEvidence(
                    ticket_id=101,
                    subject="VPN access failure",
                    status="open",
                    priority="urgent",
                    category="Network",
                    is_overdue=True,
                    is_escalated=True,
                ),
                AIFreshserviceTicketEvidence(
                    ticket_id=102,
                    subject="Printer cannot connect",
                    status="open",
                    priority="medium",
                    category="Hardware",
                    is_overdue=False,
                    is_escalated=False,
                ),
            ],
        )


class FakeSnipeItAssetRepository:
    def __init__(self):
        self.detail_limits = []

    def asset_details_for_question(self, question, *, end, limit=20):
        self.detail_limits.append(limit)
        if "asset" not in question.casefold():
            return None
        return AISnipeItAssetSetEvidence(
            matching_count=2,
            truncated=False,
            assets=[
                AISnipeItAssetEvidence(
                    asset_tag="LT-001",
                    name="Finance Laptop",
                    model="ThinkPad T14",
                    manufacturer="Lenovo",
                    category="Laptop",
                    status_label="Deployed",
                    location="Main Office",
                    is_assigned=True,
                    warranty_state="expired",
                    missing_asset_tag=False,
                ),
                AISnipeItAssetEvidence(
                    asset_tag=None,
                    name="Spare Laptop",
                    model="ThinkPad T14",
                    manufacturer="Lenovo",
                    category="Laptop",
                    status_label="Ready to Deploy",
                    location="Main Office",
                    is_assigned=False,
                    warranty_state="expiring_soon",
                    missing_asset_tag=True,
                ),
            ],
        )


class FakeZabbixDashboardService:
    def get_dashboard(self):
        return zabbix_host_dashboard()


class FakeZabbixDeviceRepository(FakeDeviceRepository):
    def get_source_record_id(self, device_id, source):
        if device_id == 42 and source == "zabbix":
            return "42"
        return None


def zabbix_device() -> AICorrelatedDeviceEvidence:
    return AICorrelatedDeviceEvidence(
        device_id=42,
        canonical_name="Server 42",
        hostname="server-42.example.com",
        correlation_confidence=95,
        linked_sources=["zabbix"],
    )


def test_service_replaces_freshservice_aggregate_metrics_with_question_specific_counts() -> None:
    async def run() -> None:
        service = AIService(
            provider=BadInvestigationProvider(),
            executive_service=FakeExecutiveService(),
            device_repository=FakeDeviceRepository([]),
            freshservice_repository=FakeFreshserviceMetricsRepository(),
        )

        response = await service.investigate(
            "How many tickets were resolved?",
            START,
            NOW,
        )

        assert response.classification.scope == "source"
        assert response.classification.source == "freshservice"
        assert "Freshservice tickets resolved in range: 7" in response.analysis.evidence
        assert not any("Freshservice tickets open" in item for item in response.analysis.evidence)
        assert any("resolved/closed" in warning.lower() for warning in response.analysis.warnings)

    asyncio.run(run())


def test_service_adds_bounded_freshservice_ticket_details_for_content_question() -> None:
    async def run() -> None:
        provider = BadInvestigationProvider()
        repository = FakeFreshserviceMetricsRepository()
        service = AIService(
            provider=provider,
            executive_service=FakeExecutiveService(),
            device_repository=FakeDeviceRepository([]),
            freshservice_repository=repository,
        )

        response = await service.investigate(
            "What are the open tickets about?",
            START,
            NOW,
        )

        assert response.classification.scope == "source"
        assert response.classification.source == "freshservice"
        assert "Freshservice matching tickets: 2" in response.analysis.evidence
        assert any("VPN access failure" in fact for fact in response.analysis.evidence)
        assert any("Printer cannot connect" in fact for fact in response.analysis.evidence)
        assert response.analysis.summary.startswith("Matched 2 Freshservice tickets")
        assert repository.detail_limits == [5]
        prompt = provider.calls[0]["prompt"]
        assert "VPN access failure" in prompt
        assert "Printer cannot connect" in prompt
        assert "ticket subjects" in prompt.lower()
        assert "requester_id" not in prompt.lower()
        assert "responder_id" not in prompt.lower()

    asyncio.run(run())


def test_service_adds_bounded_snipe_it_asset_details_for_asset_question() -> None:
    async def run() -> None:
        provider = BadInvestigationProvider()
        repository = FakeSnipeItAssetRepository()
        service = AIService(
            provider=provider,
            executive_service=FakeExecutiveService(),
            device_repository=FakeDeviceRepository([]),
            snipe_it_repository=repository,
        )

        response = await service.investigate(
            "Which Snipe-IT assets have expired warranties?",
            START,
            NOW,
        )

        assert response.classification.scope == "source"
        assert response.classification.source == "snipe_it"
        assert "Snipe-IT matching assets: 2" in response.analysis.evidence
        assert any("Finance Laptop" in fact for fact in response.analysis.evidence)
        assert any("Spare Laptop" in fact for fact in response.analysis.evidence)
        assert response.analysis.summary.startswith("Matched 2 Snipe-IT assets")
        assert repository.detail_limits == [5]
        prompt = provider.calls[0]["prompt"]
        assert "Finance Laptop" in prompt
        assert "SENSITIVE-SERIAL" not in prompt
        assert "assigned_to_id" not in prompt

    asyncio.run(run())


def test_service_adds_correlated_zabbix_host_evidence_for_named_server_question() -> None:
    async def run() -> None:
        service = AIService(
            provider=BadInvestigationProvider(),
            executive_service=FakeExecutiveService(),
            device_repository=FakeZabbixDeviceRepository([zabbix_device()]),
            zabbix_service=FakeZabbixDashboardService(),
        )

        response = await service.investigate("Why is Server 42 down?", START, NOW)

        assert response.classification.scope == "device"
        assert response.classification.source == "zabbix"
        assert "Zabbix host status: unavailable" in response.analysis.evidence
        assert any(
            "Zabbix active problem: Zabbix agent is not available" in fact
            for fact in response.analysis.evidence
        )
        assert response.analysis.likely_explanation is not None
        assert "zabbix agent is not available" in response.analysis.likely_explanation.lower()
        assert not any("Environment-level Zabbix" in fact for fact in response.analysis.evidence)

    asyncio.run(run())


def test_generic_zabbix_down_question_marks_missing_specific_host_evidence() -> None:
    async def run() -> None:
        service = AIService(
            provider=BadInvestigationProvider(),
            executive_service=FakeExecutiveService(),
            device_repository=FakeDeviceRepository([]),
        )

        response = await service.investigate("Why is the host unavailable?", START, NOW)

        assert response.classification.scope == "source"
        assert response.classification.source == "zabbix"
        assert any("specific correlated host" in warning.lower() for warning in response.analysis.warnings)
        assert response.analysis.likely_explanation is None

    asyncio.run(run())

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def test_integration_health_accepts_canonical_values_and_rejects_extra_fields() -> None:
    from app.contracts import IntegrationHealthSummary

    health = IntegrationHealthSummary(
        source="wazuh",
        status="healthy",
        observed_at=NOW,
        last_success_at=NOW,
        response_time_ms=42,
        is_stale=False,
        warnings=[],
    )

    assert health.source == "wazuh"
    assert health.status == "healthy"

    with pytest.raises(ValidationError):
        IntegrationHealthSummary(
            source="wazuh",
            status="healthy",
            observed_at=NOW,
            is_stale=False,
            warnings=[],
            raw_response={"do_not": "store this"},
        )


def test_integration_health_rejects_unknown_source_and_status() -> None:
    from app.contracts import IntegrationHealthSummary

    with pytest.raises(ValidationError):
        IntegrationHealthSummary(
            source="unknown",
            status="healthy",
            observed_at=NOW,
            is_stale=False,
        )

    with pytest.raises(ValidationError):
        IntegrationHealthSummary(
            source="wazuh",
            status="broken",
            observed_at=NOW,
            is_stale=False,
        )


def test_executive_summary_accepts_scalar_metrics_only() -> None:
    from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary

    health = IntegrationHealthSummary(
        source="freshservice",
        status="degraded",
        observed_at=NOW,
        last_success_at=NOW,
        response_time_ms=150,
        is_stale=True,
        warnings=["Ticket data is stale."],
    )

    summary = ExecutiveSourceSummary(
        source="freshservice",
        observed_at=NOW,
        is_stale=True,
        health=health,
        metrics={
            "open_tickets": 12,
            "sla_risk": 3,
            "availability_note": "partial",
            "has_critical_ticket": True,
            "optional_value": None,
        },
        warnings=["Ticket data is stale."],
    )

    assert summary.metrics["open_tickets"] == 12

    with pytest.raises(ValidationError):
        ExecutiveSourceSummary(
            source="freshservice",
            observed_at=NOW,
            is_stale=True,
            health=health,
            metrics={"raw_tickets": [{"id": 1}]},
        )


def test_executive_summary_rejects_source_mismatch_and_unbounded_metrics() -> None:
    from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary

    health = IntegrationHealthSummary(
        source="zabbix",
        status="healthy",
        observed_at=NOW,
        is_stale=False,
    )

    with pytest.raises(ValidationError, match="health source"):
        ExecutiveSourceSummary(
            source="wazuh",
            observed_at=NOW,
            is_stale=False,
            health=health,
            metrics={},
        )

    with pytest.raises(ValidationError):
        ExecutiveSourceSummary(
            source="zabbix",
            observed_at=NOW,
            is_stale=False,
            health=health,
            metrics={f"metric_{index}": index for index in range(33)},
        )

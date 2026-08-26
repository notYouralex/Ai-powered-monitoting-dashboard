import math

from app.ai.models import (
    AIAffectedSource,
    AIAttentionSignal,
    AICorrelatedDeviceEvidence,
    AIExecutiveEvidence,
    AIExecutiveSummaryEvidence,
    AIInvestigationEvidence,
    AIQuestionClassification,
    AISourceEvidence,
)
from app.contracts import ExecutiveSourceSummary, IntegrationSource
from app.dashboard.executive.models import ExecutiveDashboardResponse


_ALLOWED_METRICS: dict[IntegrationSource, tuple[str, ...]] = {
    "wazuh": (
        "agents_total",
        "agents_active",
        "agents_disconnected",
        "alerts_high",
        "alerts_critical",
        "vulnerabilities_high",
        "vulnerabilities_critical",
        "vulnerable_agents",
    ),
    "zabbix": (
        "hosts_total",
        "interfaces_unavailable",
        "problems_total",
        "problems_high",
        "problems_disaster",
        "problems_unacknowledged",
    ),
    "snipe_it": (
        "assets_total",
        "assets_unassigned",
        "assets_missing_serial",
        "assets_missing_asset_tag",
        "warranty_expired",
        "warranty_expiring_soon",
    ),
    "freshservice": (
        "tickets_open",
        "tickets_pending",
        "high_priority_open",
        "due_today",
        "overdue_open",
        "escalated_open",
    ),
}

_ATTENTION_METRICS: dict[IntegrationSource, tuple[str, ...]] = {
    "wazuh": (
        "agents_disconnected",
        "alerts_high",
        "alerts_critical",
        "vulnerabilities_high",
        "vulnerabilities_critical",
        "vulnerable_agents",
    ),
    "zabbix": (
        "interfaces_unavailable",
        "problems_high",
        "problems_disaster",
        "problems_unacknowledged",
    ),
    "snipe_it": (
        "assets_unassigned",
        "assets_missing_serial",
        "assets_missing_asset_tag",
        "warranty_expired",
        "warranty_expiring_soon",
    ),
    "freshservice": (
        "tickets_open",
        "tickets_pending",
        "high_priority_open",
        "due_today",
        "overdue_open",
        "escalated_open",
    ),
}


def build_executive_evidence(
    dashboard: ExecutiveDashboardResponse,
) -> AIExecutiveEvidence:
    """Project normalized Executive data into a small numeric-only AI evidence bundle."""

    sources = [_source_evidence(summary) for summary in dashboard.sources]

    return AIExecutiveEvidence(
        observed_at=dashboard.observed_at,
        range_start=dashboard.range_start,
        range_end=dashboard.range_end,
        sources=sources,
    )


def build_executive_summary_evidence(
    dashboard: ExecutiveDashboardResponse,
) -> AIExecutiveSummaryEvidence:
    """Derive nonzero adverse signals for the small Executive summary model."""

    signals = []
    affected_sources = []
    for summary in dashboard.sources:
        source_signals, affected_source = _summary_source_evidence(summary)
        signals.extend(source_signals)
        if affected_source is not None:
            affected_sources.append(affected_source)

    return AIExecutiveSummaryEvidence(
        observed_at=dashboard.observed_at,
        range_start=dashboard.range_start,
        range_end=dashboard.range_end,
        attention_signals=signals,
        affected_sources=affected_sources,
    )


def build_source_summary_evidence(
    dashboard: ExecutiveDashboardResponse,
    source: IntegrationSource,
) -> AIExecutiveSummaryEvidence:
    """Derive bounded adverse signals for one normalized Executive source summary."""

    summary = next(item for item in dashboard.sources if item.source == source)
    signals, affected_source = _summary_source_evidence(summary)
    return AIExecutiveSummaryEvidence(
        observed_at=dashboard.observed_at,
        range_start=dashboard.range_start,
        range_end=dashboard.range_end,
        attention_signals=signals,
        affected_sources=[affected_source] if affected_source is not None else [],
    )


def build_investigation_evidence(
    dashboard: ExecutiveDashboardResponse,
    classification: AIQuestionClassification,
    *,
    device: AICorrelatedDeviceEvidence | None,
) -> AIInvestigationEvidence:
    """Select only normalized source/device evidence relevant to one classified question."""

    selected_sources: list[IntegrationSource]
    limitations = [
        "Evidence contains normalized aggregate metrics and source health, not raw event, ticket, or asset records."
    ]
    if classification.scope == "environment":
        selected_sources = [summary.source for summary in dashboard.sources]
    elif classification.scope == "source":
        selected_sources = [classification.source] if classification.source is not None else []
    else:
        if device is None:
            raise ValueError("unique device investigation requires device evidence")
        if classification.source is not None:
            selected_sources = (
                [classification.source]
                if classification.source in device.linked_sources
                else []
            )
            if not selected_sources:
                limitations.append(
                    "The requested source is not linked to the correlated device."
                )
        else:
            selected_sources = list(device.linked_sources)
        limitations.append(
            "Selected source metrics are environment-level and are not attributed to the correlated device."
        )

    summaries = {summary.source: summary for summary in dashboard.sources}
    if classification.scope == "environment":
        sources = [
            source_evidence
            for source in selected_sources
            if source in summaries
            and (source_evidence := _environment_source_evidence(summaries[source])) is not None
        ]
    else:
        sources = [
            _source_evidence(summaries[source])
            for source in selected_sources
            if source in summaries
        ]
    return AIInvestigationEvidence(
        observed_at=dashboard.observed_at,
        range_start=dashboard.range_start,
        range_end=dashboard.range_end,
        classification=classification,
        sources=sources,
        device=device,
        limitations=limitations,
    )


def _environment_source_evidence(
    summary: ExecutiveSourceSummary,
) -> AISourceEvidence | None:
    metrics = {}
    for key in _ATTENTION_METRICS[summary.source]:
        value = summary.metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            continue
        metrics[key] = value

    is_stale = summary.is_stale or summary.health.is_stale
    if not metrics and summary.health.status == "healthy" and not is_stale:
        return None

    return AISourceEvidence(
        source=summary.source,
        status=summary.health.status,
        is_stale=is_stale,
        metrics=metrics,
    )


def _source_evidence(summary: ExecutiveSourceSummary) -> AISourceEvidence:
    metrics = {}
    for key in _ALLOWED_METRICS[summary.source]:
        value = summary.metrics.get(key)
        if isinstance(value, bool) or isinstance(value, int):
            metrics[key] = value
        elif isinstance(value, float) and math.isfinite(value):
            metrics[key] = value
    return AISourceEvidence(
        source=summary.source,
        status=summary.health.status,
        is_stale=summary.is_stale or summary.health.is_stale,
        metrics=metrics,
    )


def _summary_source_evidence(
    summary: ExecutiveSourceSummary,
) -> tuple[list[AIAttentionSignal], AIAffectedSource | None]:
    signals = []
    for key in _ATTENTION_METRICS[summary.source]:
        value = summary.metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            continue
        signals.append(
            AIAttentionSignal(
                source=summary.source,
                metric=key,
                value=value,
            )
        )

    is_stale = summary.is_stale or summary.health.is_stale
    affected_source = None
    if summary.health.status != "healthy" or is_stale:
        affected_source = AIAffectedSource(
            source=summary.source,
            status=summary.health.status,
            is_stale=is_stale,
        )
    return signals, affected_source

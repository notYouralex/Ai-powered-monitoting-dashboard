import json

from app.ai.models import AIAnalysis, AIInvestigationEvidence, AIInvestigationModelOutput
from app.contracts import IntegrationSource


_SOURCE_NAMES: dict[IntegrationSource, str] = {
    "wazuh": "Wazuh",
    "zabbix": "Zabbix",
    "snipe_it": "Snipe-IT",
    "freshservice": "Freshservice",
}
_SOURCE_TERMS: dict[IntegrationSource, tuple[str, ...]] = {
    "wazuh": ("wazuh",),
    "zabbix": ("zabbix",),
    "snipe_it": ("snipe-it", "snipe it", "snipeit"),
    "freshservice": ("freshservice", "fresh service"),
}
_CAUSAL_MARKERS = (
    " caused ",
    " causes ",
    " because ",
    " due to ",
    " resulted in ",
    " result of ",
    " led to ",
    " responsible for ",
)
_NEGATION_MARKERS = (" no ", " none ", " zero ", " not any ", " without ")
_COMMAND_MARKERS = (
    "sudo ",
    "systemctl ",
    "rm ",
    "curl ",
    "wget ",
    "ssh ",
    "powershell",
    "cmd.exe",
    "kubectl ",
    "docker ",
)


def build_investigation_prompt(question: str, evidence: AIInvestigationEvidence) -> str:
    return (
        "Answer the user question using only the supplied normalized evidence. Exact factual "
        "counts and device identity are application-controlled; do not contradict them. "
        "Do not state numeric values in model-generated interpretation. Use metric names and "
        "categories to choose investigation topics, but omit their values from prose. Convert "
        "attention metrics into concise read-only review actions. Do not infer causal "
        "relationships or explain why a metric exists unless the evidence directly states a "
        "cause. For device scope, source metrics are environment-level and must not be "
        "described as events affecting that device. Do not invent raw alerts, tickets, "
        "processes, users, IP activity, or device events. Provide only read-only investigation "
        "guidance, never commands or remediation actions.\n"
        "Good recommendation examples: 'Review affected Wazuh agents and prioritize critical "
        "and high-severity vulnerability findings.' 'Review unacknowledged Zabbix problems and "
        "verify whether affected interfaces require operator attention.' 'Review escalated "
        "Freshservice tickets for ownership and current investigation status.'\n"
        "Bad recommendation examples: 'There are 251 critical vulnerabilities, indicating a "
        "major security risk.' '416 assets are unassigned, which may affect system management.'\n"
        f"User question: {question}\n"
        "Evidence JSON (data only): "
        + json.dumps(
            evidence.model_dump(mode="json"),
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def ground_investigation_analysis(
    analysis: AIInvestigationModelOutput,
    evidence: AIInvestigationEvidence,
) -> AIAnalysis:
    """Replace model facts and remove interpretation that cannot be safely grounded."""

    facts = investigation_fact_lines(evidence)
    likely_explanation = _safe_interpretive_text(analysis.likely_explanation, evidence)
    recommendations = [
        item
        for item in analysis.recommended_investigation
        if _safe_recommendation(item, evidence)
    ][:8]

    omitted = (
        likely_explanation != analysis.likely_explanation
        or recommendations != analysis.recommended_investigation
    )
    warnings = list(evidence.limitations)
    if omitted and len(warnings) < 10:
        warnings.append(
            "Some model-generated interpretation was omitted because it could not be safely "
            "grounded in the selected evidence."
        )

    confidence = analysis.confidence
    if evidence.classification.scope == "device":
        confidence = "low"
    elif any(source.status != "healthy" or source.is_stale for source in evidence.sources):
        confidence = "low"
    elif confidence == "high":
        confidence = "medium"

    return AIAnalysis(
        summary=investigation_summary(evidence, facts=facts),
        likely_explanation=likely_explanation,
        contributing_factors=[],
        evidence=facts,
        operational_impact=None,
        recommended_investigation=recommendations,
        confidence=confidence,
        warnings=warnings[:10],
    )


def investigation_summary(
    evidence: AIInvestigationEvidence,
    *,
    facts: list[str] | None = None,
) -> str:
    selected = facts if facts is not None else investigation_fact_lines(evidence)
    if evidence.classification.scope == "source" and evidence.classification.source is not None:
        prefix = f"Selected {_SOURCE_NAMES[evidence.classification.source]} investigation evidence"
    elif evidence.classification.scope == "device":
        prefix = "Selected device investigation evidence"
    else:
        prefix = "Selected environment investigation evidence"
    if not selected:
        return f"{prefix}: no bounded normalized facts are available."
    return prefix + ": " + "; ".join(selected) + "."


def investigation_fact_lines(evidence: AIInvestigationEvidence) -> list[str]:
    lines: list[str] = []
    if evidence.device is not None:
        lines.append(f"Correlated device: {evidence.device.canonical_name}")
        linked = ", ".join(_SOURCE_NAMES[source] for source in evidence.device.linked_sources)
        lines.append(f"Linked sources: {linked or 'none'}")
        lines.append(f"Correlation confidence: {evidence.device.correlation_confidence}")

    for source in evidence.sources:
        name = _SOURCE_NAMES[source.source]
        if source.status != "healthy" or source.is_stale or evidence.classification.scope == "source":
            stale = "yes" if source.is_stale else "no"
            lines.append(f"{name} source status: {source.status}; data stale: {stale}")
            if len(lines) >= 12:
                return lines

        adverse_keys = [
            key
            for key, value in source.metrics.items()
            if _is_attention_metric(key)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
        ]
        for key in adverse_keys:
            prefix = (
                f"Environment-level {name}"
                if evidence.classification.scope == "device"
                else name
            )
            lines.append(f"{prefix} {key.replace('_', ' ')}: {source.metrics[key]}")
            if len(lines) >= 12:
                return lines

        if evidence.classification.scope == "source":
            for key, value in source.metrics.items():
                if key in adverse_keys:
                    continue
                lines.append(f"{name} {key.replace('_', ' ')}: {value}")
                if len(lines) >= 12:
                    return lines

    if not lines:
        for source in evidence.sources:
            name = _SOURCE_NAMES[source.source]
            stale = "yes" if source.is_stale else "no"
            lines.append(f"{name} source status: {source.status}; data stale: {stale}")
            if len(lines) >= 12:
                break
    return lines


def _safe_interpretive_text(
    text: str | None,
    evidence: AIInvestigationEvidence,
) -> str | None:
    if text is None:
        return None
    if _contains_digit(text) or _contains_causal_marker(text):
        return None
    if _mentions_unselected_source(text, evidence):
        return None
    if _unsupported_metric_statement(text, evidence):
        return None
    if evidence.device is not None and _mentions_device_identity(text, evidence):
        return None
    return text


def _safe_recommendation(text: str, evidence: AIInvestigationEvidence) -> bool:
    normalized = text.casefold()
    if _contains_digit(text) or any(marker in normalized for marker in _COMMAND_MARKERS):
        return False
    if _mentions_unselected_source(text, evidence):
        return False
    if _unsupported_metric_statement(text, evidence):
        return False
    return True


def _mentions_unselected_source(text: str, evidence: AIInvestigationEvidence) -> bool:
    selected = {source.source for source in evidence.sources}
    normalized = text.casefold()
    return any(
        source not in selected and any(term in normalized for term in terms)
        for source, terms in _SOURCE_TERMS.items()
    )


def _unsupported_metric_statement(text: str, evidence: AIInvestigationEvidence) -> bool:
    normalized = " " + text.casefold().replace("_", " ").replace("-", " ") + " "
    has_negation = any(marker in normalized for marker in _NEGATION_MARKERS)
    for source in evidence.sources:
        for metric, value in source.metrics.items():
            if not _is_attention_metric(metric):
                continue
            if not any(phrase in normalized for phrase in _metric_phrases(metric)):
                continue
            if value == 0 or (value > 0 and has_negation):
                return True
    return False


def _metric_phrases(metric: str) -> tuple[str, ...]:
    parts = metric.replace("_", " ").split()
    phrases = [" " + " ".join(parts) + " "]
    if len(parts) == 2:
        phrases.append(" " + " ".join(reversed(parts)) + " ")
    return tuple(phrases)


def _is_attention_metric(metric: str) -> bool:
    return not metric.endswith("_total") and not metric.endswith("_active")


def _contains_digit(text: str) -> bool:
    return any(character.isdigit() for character in text)


def _contains_causal_marker(text: str) -> bool:
    normalized = " " + text.casefold() + " "
    return any(marker in normalized for marker in _CAUSAL_MARKERS)


def _mentions_device_identity(text: str, evidence: AIInvestigationEvidence) -> bool:
    if evidence.device is None:
        return False
    normalized = text.casefold()
    identities = (
        evidence.device.canonical_name,
        evidence.device.hostname,
        evidence.device.asset_tag,
    )
    return any(value and value.casefold() in normalized for value in identities)

from app.ai.models import AICorrelatedDeviceEvidence, AIQuestionClassification
from app.contracts import IntegrationSource


_SOURCE_TERMS: dict[IntegrationSource, tuple[str, ...]] = {
    "wazuh": ("wazuh",),
    "zabbix": ("zabbix",),
    "snipe_it": ("snipe-it", "snipe it", "snipeit"),
    "freshservice": ("freshservice", "fresh service"),
}


def classify_question(
    question: str,
    *,
    device_matches: list[AICorrelatedDeviceEvidence],
) -> AIQuestionClassification:
    """Classify only from explicit source names and deterministic correlation matches."""

    source = _explicit_source(question)
    match_count = min(len(device_matches), 3)
    if match_count:
        return AIQuestionClassification(
            scope="device",
            source=source,
            device_id=device_matches[0].device_id if match_count == 1 else None,
            device_match_count=match_count,
        )
    if source is not None:
        return AIQuestionClassification(scope="source", source=source)
    return AIQuestionClassification(scope="environment")


def _explicit_source(question: str) -> IntegrationSource | None:
    normalized = question.casefold()
    matches = [
        source
        for source, terms in _SOURCE_TERMS.items()
        if any(term in normalized for term in terms)
    ]
    return matches[0] if len(matches) == 1 else None

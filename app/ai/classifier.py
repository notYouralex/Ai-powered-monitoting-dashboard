import re

from app.ai.models import AICorrelatedDeviceEvidence, AIQuestionClassification
from app.contracts import IntegrationSource


_EXPLICIT_SOURCE_TERMS: dict[IntegrationSource, tuple[str, ...]] = {
    "wazuh": ("wazuh",),
    "zabbix": ("zabbix",),
    "snipe_it": ("snipe-it", "snipe it", "snipeit"),
    "freshservice": ("freshservice", "fresh service"),
}
_DOMAIN_SOURCE_TERMS: dict[IntegrationSource, tuple[str, ...]] = {
    "wazuh": (
        "alert",
        "alerts",
        "vulnerability",
        "vulnerabilities",
        "mitre",
        "security",
        "malware",
        "agent",
        "agents",
    ),
    "zabbix": (
        "host",
        "hosts",
        "server",
        "servers",
        "cpu",
        "memory",
        "disk",
        "interface",
        "interfaces",
        "availability",
        "unavailable",
        "down",
    ),
    "snipe_it": (
        "asset",
        "assets",
        "warranty",
        "warranties",
        "serial",
        "inventory",
        "asset tag",
    ),
    "freshservice": (
        "ticket",
        "tickets",
        "sla",
        "overdue",
        "resolved",
        "closed",
        "pending",
        "incident",
        "incidents",
    ),
}
_STRONG_SOURCE_TERMS: dict[IntegrationSource, tuple[str, ...]] = {
    "wazuh": (
        "alert",
        "alerts",
        "vulnerability",
        "vulnerabilities",
        "mitre",
        "security",
        "malware",
    ),
    "zabbix": (
        "host",
        "hosts",
        "server",
        "servers",
        "cpu",
        "memory",
        "disk",
        "interface",
        "interfaces",
        "availability",
    ),
    "snipe_it": (
        "asset",
        "assets",
        "warranty",
        "warranties",
        "serial",
        "inventory",
        "asset tag",
    ),
    "freshservice": (
        "ticket",
        "tickets",
        "sla",
        "incident",
        "incidents",
    ),
}
_ENVIRONMENT_MONITORING_PHRASES = (
    "needs attention",
    "need attention",
    "monitoring environment",
    "monitored environment",
    "overall environment",
    "overall health",
    "overall status",
    "source health",
    "source status",
    "monitoring status",
    "current issues",
    "active issues",
    "what is happening",
    "what's happening",
    "what should i investigate",
    "what requires investigation",
)
_WORD_RE = re.compile(r"[a-z0-9]+")


def is_monitoring_question(
    question: str,
    *,
    device_matches: list[AICorrelatedDeviceEvidence],
) -> bool:
    """Return whether a question has deterministic monitoring-domain evidence."""

    if device_matches:
        return True
    if _explicit_source(question) is not None or _inferred_source(question) is not None:
        return True

    normalized = " ".join(_WORD_RE.findall(question.casefold()))
    padded = f" {normalized} "
    if any(_contains_term(padded, phrase) for phrase in _ENVIRONMENT_MONITORING_PHRASES):
        return True

    domain_hits = sum(
        _contains_term(padded, term)
        for terms in _DOMAIN_SOURCE_TERMS.values()
        for term in terms
    )
    return domain_hits >= 2


def classify_question(
    question: str,
    *,
    device_matches: list[AICorrelatedDeviceEvidence],
) -> AIQuestionClassification:
    """Route explicit names first, then bounded domain terms and deterministic device matches."""

    source = _explicit_source(question) or _inferred_source(question)
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
        for source, terms in _EXPLICIT_SOURCE_TERMS.items()
        if any(term in normalized for term in terms)
    ]
    return matches[0] if len(matches) == 1 else None


def _inferred_source(question: str) -> IntegrationSource | None:
    normalized = " ".join(_WORD_RE.findall(question.casefold()))
    padded = f" {normalized} "
    scores = {
        source: sum(_contains_term(padded, term) for term in terms)
        for source, terms in _DOMAIN_SOURCE_TERMS.items()
    }
    eligible = {
        source: score
        for source, score in scores.items()
        if score >= 2
        or any(
            _contains_term(padded, term)
            for term in _STRONG_SOURCE_TERMS[source]
        )
    }
    highest = max(eligible.values(), default=0)
    if highest == 0:
        return None
    winners = [source for source, score in eligible.items() if score == highest]
    return winners[0] if len(winners) == 1 else None


def _contains_term(padded_question: str, term: str) -> bool:
    normalized_term = " ".join(_WORD_RE.findall(term.casefold()))
    return f" {normalized_term} " in padded_question

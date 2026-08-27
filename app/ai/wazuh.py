import re
from app.ai.models import (
    AIWazuhAgentEvidence,
    AIWazuhAlertEvidence,
    AIWazuhDetailEvidence,
    AIWazuhNamedCountEvidence,
    AIWazuhVulnerabilityEvidence,
)
from app.integrations.wazuh.models import (
    WazuhAgent,
    WazuhAlert,
    WazuhDashboardResponse,
    WazuhVulnerability,
)


_COUNT_TERMS = ("how many", "count", "number of")
_ALERT_TERMS = ("alert", "alerts", "security event", "security events", "malware")
_VULNERABILITY_TERMS = ("vulnerability", "vulnerabilities", "cve", "cves")
_AGENT_TERMS = (
    "agent",
    "agents",
    "disconnected",
    "pending",
    "never connected",
    "never-connected",
)
_MITRE_TERMS = ("mitre", "tactic", "tactics", "technique", "techniques")
_HEALTH_TERMS = ("stale", "degraded", "freshness", "source status")
_WORD_RE = re.compile(r"[a-z0-9]+")


def should_load_wazuh_details(question: str) -> bool:
    """Return whether a Wazuh question needs bounded record-level evidence."""

    if _contains_any_term(question, _COUNT_TERMS):
        return False
    if any(
        _contains_any_term(question, terms)
        for terms in (_ALERT_TERMS, _VULNERABILITY_TERMS, _AGENT_TERMS, _MITRE_TERMS)
    ):
        return True
    return _contains_term(question, "wazuh") and not _contains_any_term(question, _HEALTH_TERMS)


def build_wazuh_detail_evidence(
    question: str,
    dashboard: WazuhDashboardResponse,
    *,
    agent_id: str | None = None,
    limit: int = 5,
) -> AIWazuhDetailEvidence | None:
    """Project normalized Wazuh dashboard data into small AI-safe detail evidence."""

    if limit < 1 or limit > 10:
        raise ValueError("Wazuh AI detail limit must be between 1 and 10")
    if not should_load_wazuh_details(question):
        return None

    wants_alerts = _contains_any_term(question, _ALERT_TERMS)
    wants_vulnerabilities = _contains_any_term(question, _VULNERABILITY_TERMS)
    wants_agents = _contains_any_term(question, _AGENT_TERMS)
    wants_mitre = _contains_any_term(question, _MITRE_TERMS)
    if agent_id is not None:
        wants_alerts = True
        wants_vulnerabilities = True
        wants_agents = True
        wants_mitre = False
    elif not any((wants_alerts, wants_vulnerabilities, wants_agents, wants_mitre)):
        wants_alerts = wants_vulnerabilities = wants_agents = wants_mitre = True

    alerts = (
        _select_alerts(question, dashboard.recent_alerts, agent_id=agent_id)
        if wants_alerts
        else []
    )
    vulnerabilities = (
        _select_vulnerabilities(
            question,
            dashboard.vulnerabilities.recent,
            agent_id=agent_id,
        )
        if wants_vulnerabilities
        else []
    )
    agents = (
        _select_agents(question, dashboard.agents, agent_id=agent_id)
        if wants_agents
        else []
    )

    tactics = []
    techniques = []
    if wants_mitre and agent_id is None:
        wants_tactics = _contains_term(question, "tactic") or _contains_term(question, "tactics")
        wants_techniques = _contains_term(question, "technique") or _contains_term(question, "techniques")
        if not wants_tactics and not wants_techniques:
            wants_tactics = wants_techniques = True
        if wants_tactics:
            tactics = [
                AIWazuhNamedCountEvidence(name=_bounded(item.name, 128), count=item.count)
                for item in dashboard.mitre.tactics[:limit]
            ]
        if wants_techniques:
            techniques = [
                AIWazuhNamedCountEvidence(name=_bounded(item.name, 128), count=item.count)
                for item in dashboard.mitre.techniques[:limit]
            ]

    return AIWazuhDetailEvidence(
        recent_alert_matches=len(alerts),
        alerts=[_alert_evidence(item) for item in alerts[:limit]],
        recent_vulnerability_matches=len(vulnerabilities),
        vulnerabilities=[_vulnerability_evidence(item) for item in vulnerabilities[:limit]],
        agent_matches=len(agents),
        agents=[_agent_evidence(item) for item in agents[:limit]],
        mitre_tactics=tactics,
        mitre_techniques=techniques,
    )


def _select_alerts(
    question: str,
    alerts: list[WazuhAlert],
    *,
    agent_id: str | None,
) -> list[WazuhAlert]:
    selected = [item for item in alerts if agent_id is None or item.agent_id == agent_id]
    critical = _contains_term(question, "critical")
    high = _contains_term(question, "high")
    if critical and high:
        selected = [item for item in selected if item.rule_level >= 12]
    elif critical:
        selected = [item for item in selected if item.rule_level >= 15]
    elif high:
        selected = [item for item in selected if 12 <= item.rule_level <= 14]
    return sorted(selected, key=lambda item: (item.rule_level, item.timestamp), reverse=True)


def _select_vulnerabilities(
    question: str,
    vulnerabilities: list[WazuhVulnerability],
    *,
    agent_id: str | None,
) -> list[WazuhVulnerability]:
    selected = [
        item
        for item in vulnerabilities
        if agent_id is None or item.agent_id == agent_id
    ]
    critical = _contains_term(question, "critical")
    high = _contains_term(question, "high")
    if critical and high:
        selected = [
            item for item in selected if item.severity.casefold() in {"critical", "high"}
        ]
    elif critical:
        selected = [item for item in selected if item.severity.casefold() == "critical"]
    elif high:
        selected = [item for item in selected if item.severity.casefold() == "high"]

    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    return sorted(
        selected,
        key=lambda item: (
            severity_rank.get(item.severity.casefold(), 0),
            item.score if item.score is not None else -1.0,
            item.detected_at.timestamp() if item.detected_at is not None else float("-inf"),
        ),
        reverse=True,
    )


def _select_agents(
    question: str,
    agents: list[WazuhAgent],
    *,
    agent_id: str | None,
) -> list[WazuhAgent]:
    selected = [item for item in agents if agent_id is None or item.agent_id == agent_id]
    if agent_id is None:
        if _contains_term(question, "disconnected"):
            selected = [item for item in selected if item.status == "disconnected"]
        elif _contains_term(question, "pending"):
            selected = [item for item in selected if item.status == "pending"]
        elif _contains_term(question, "never connected") or _contains_term(question, "never-connected"):
            selected = [item for item in selected if item.status == "never_connected"]
        elif _contains_term(question, "active"):
            selected = [item for item in selected if item.status == "active"]
        else:
            selected = [item for item in selected if item.status != "active"]

    rank = {
        "disconnected": 0,
        "never_connected": 1,
        "pending": 2,
        "unknown": 3,
        "active": 4,
    }
    return sorted(selected, key=lambda item: (rank.get(item.status, 5), item.name.casefold()))


def _alert_evidence(alert: WazuhAlert) -> AIWazuhAlertEvidence:
    return AIWazuhAlertEvidence(
        timestamp=alert.timestamp,
        rule_level=alert.rule_level,
        description=_bounded(alert.description, 180),
        agent_name=_bounded_optional(alert.agent_name, 128),
        groups=[_bounded(value, 64) for value in alert.groups[:5]],
    )


def _vulnerability_evidence(
    vulnerability: WazuhVulnerability,
) -> AIWazuhVulnerabilityEvidence:
    return AIWazuhVulnerabilityEvidence(
        vulnerability_id=_bounded(vulnerability.vulnerability_id, 128),
        severity=_bounded(vulnerability.severity, 32),
        score=vulnerability.score,
        detected_at=vulnerability.detected_at,
        agent_name=_bounded_optional(vulnerability.agent_name, 128),
        package_name=_bounded_optional(vulnerability.package_name, 128),
        package_version=_bounded_optional(vulnerability.package_version, 128),
        description=_bounded_optional(vulnerability.description, 180),
    )


def _agent_evidence(agent: WazuhAgent) -> AIWazuhAgentEvidence:
    return AIWazuhAgentEvidence(
        name=_bounded(agent.name, 128),
        status=agent.status,
        last_keep_alive=agent.last_keep_alive,
        os_name=_bounded_optional(agent.os_name, 128),
        os_version=_bounded_optional(agent.os_version, 128),
        os_platform=_bounded_optional(agent.os_platform, 64),
        os_arch=_bounded_optional(agent.os_arch, 64),
        groups=[_bounded(value, 64) for value in agent.groups[:5]],
    )


def _bounded(value: str, limit: int) -> str:
    return value.strip()[:limit]


def _bounded_optional(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped[:limit] if stripped else None


def _contains_any_term(question: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(question, term) for term in terms)


def _contains_term(question: str, term: str) -> bool:
    normalized_question = " ".join(_WORD_RE.findall(question.casefold()))
    normalized_term = " ".join(_WORD_RE.findall(term.casefold()))
    return f" {normalized_term} " in f" {normalized_question} "

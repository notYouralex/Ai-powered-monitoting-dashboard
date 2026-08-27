from app.ai.classifier import classify_question, is_monitoring_question
from app.ai.models import AICorrelatedDeviceEvidence


def device(device_id: int, name: str) -> AICorrelatedDeviceEvidence:
    return AICorrelatedDeviceEvidence(
        device_id=device_id,
        canonical_name=name,
        correlation_confidence=90,
        linked_sources=["wazuh", "zabbix"],
    )


def test_classifier_prefers_unique_correlated_device_and_keeps_explicit_source() -> None:
    result = classify_question(
        "Explain the Wazuh alerts affecting PC-023",
        device_matches=[device(23, "PC-023")],
    )

    assert result.scope == "device"
    assert result.source == "wazuh"
    assert result.device_id == 23
    assert result.device_match_count == 1


def test_classifier_selects_explicit_source_without_device_match() -> None:
    result = classify_question(
        "Which Freshservice tickets need attention?",
        device_matches=[],
    )

    assert result.scope == "source"
    assert result.source == "freshservice"
    assert result.device_id is None


def test_classifier_defaults_general_questions_to_environment() -> None:
    result = classify_question("What needs attention today?", device_matches=[])

    assert result.scope == "environment"
    assert result.source is None
    assert result.device_match_count == 0


def test_classifier_marks_multiple_device_matches_as_ambiguous() -> None:
    result = classify_question(
        "Explain shared-host",
        device_matches=[device(1, "shared-host"), device(2, "shared-host")],
    )

    assert result.scope == "device"
    assert result.device_id is None
    assert result.device_match_count == 2


def test_classifier_routes_ticket_language_to_freshservice() -> None:
    for question in (
        "How many tickets were resolved?",
        "How many tickets are closed, overdue, pending, and open?",
        "Show overdue ticket information",
        "What is the SLA status?",
    ):
        result = classify_question(question, device_matches=[])
        assert result.scope == "source"
        assert result.source == "freshservice"


def test_classifier_routes_infrastructure_language_to_zabbix() -> None:
    for question in (
        "Why is the server down?",
        "Why is the host unavailable?",
        "Which hosts have high CPU or memory?",
    ):
        result = classify_question(question, device_matches=[])
        assert result.scope == "source"
        assert result.source == "zabbix"


def test_classifier_routes_security_and_asset_language_to_owned_sources() -> None:
    wazuh = classify_question("Which security alerts need attention?", device_matches=[])
    snipe_it = classify_question("Which assets have expired warranties?", device_matches=[])

    assert wazuh.scope == "source"
    assert wazuh.source == "wazuh"
    assert snipe_it.scope == "source"
    assert snipe_it.source == "snipe_it"


def test_classifier_explicit_source_wins_over_domain_terms() -> None:
    result = classify_question("Show Wazuh alerts for this host", device_matches=[])

    assert result.scope == "source"
    assert result.source == "wazuh"


def test_classifier_does_not_guess_when_domain_terms_tie_or_context_is_too_generic() -> None:
    ambiguous = classify_question("Why is the agent unavailable?", device_matches=[])
    generic = classify_question("Why is the port closed?", device_matches=[])

    assert ambiguous.scope == "environment"
    assert ambiguous.source is None
    assert generic.scope == "environment"
    assert generic.source is None


def test_scope_guard_allows_monitoring_sources_devices_and_environment_phrases() -> None:
    assert is_monitoring_question("What needs attention today?", device_matches=[]) is True
    assert is_monitoring_question("Why is the agent unavailable?", device_matches=[]) is True
    assert is_monitoring_question("How many open tickets are there?", device_matches=[]) is True
    assert is_monitoring_question(
        "How is PC-023?",
        device_matches=[device(23, "PC-023")],
    ) is True


def test_scope_guard_rejects_unrelated_general_or_creative_questions() -> None:
    for question in (
        "What is the capital of France?",
        "Write me a poem about the ocean.",
        "Who won the World Cup?",
        "Explain quantum physics.",
        "Why is the port closed?",
    ):
        assert is_monitoring_question(question, device_matches=[]) is False

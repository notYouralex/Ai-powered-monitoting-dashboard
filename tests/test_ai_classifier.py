from app.ai.classifier import classify_question
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

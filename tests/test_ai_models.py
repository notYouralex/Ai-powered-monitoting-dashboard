import pytest
from pydantic import ValidationError

from app.ai.models import AIAnalysis, AIQueryRequest
from app.core.config import Settings


def test_ai_query_request_strips_and_bounds_question() -> None:
    request = AIQueryRequest(question="  What needs attention?  ")

    assert request.question == "What needs attention?"

    with pytest.raises(ValidationError):
        AIQueryRequest(question="x" * 1001)


def test_ai_analysis_forbids_unexpected_fields_and_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        AIAnalysis(summary="ok", confidence="certain")

    with pytest.raises(ValidationError):
        AIAnalysis(summary="ok", confidence="low", unexpected="value")


def test_ai_settings_are_local_only_and_model_selection_is_configurable() -> None:
    settings = Settings(
        ai_enabled=True,
        ai_summary_model="gemma3:1b-it-qat",
        ai_investigation_model="qwen3:1.7b",
        _env_file=None,
    )

    assert str(settings.ai_ollama_base_url) == "http://127.0.0.1:11434/"
    assert settings.ai_summary_model == "gemma3:1b-it-qat"
    assert settings.ai_investigation_model == "qwen3:1.7b"
    assert settings.ai_context_size == 1024
    assert settings.ai_summary_cache_seconds == 300

    with pytest.raises(ValidationError):
        Settings(ai_ollama_base_url="https://example.com", _env_file=None)

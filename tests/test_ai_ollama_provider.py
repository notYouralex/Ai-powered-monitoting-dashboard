import json

import httpx
import pytest

from app.ai.errors import AIError
from app.ai.models import AIAnalysis
from app.ai.ollama import OllamaProvider
from app.core.config import Settings


def make_settings(**overrides) -> Settings:
    values = {
        "ai_enabled": True,
        "ai_summary_model": "gemma3:1b-it-qat",
        "ai_investigation_model": "qwen3:1.7b",
        "ai_context_size": 1024,
        "ai_max_output_tokens": 256,
        "ai_timeout_seconds": 30,
        "ai_keep_alive_seconds": 0,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def valid_analysis_json() -> str:
    return AIAnalysis(
        summary="Two authentication failures require review.",
        likely_explanation="The evidence supports suspicious authentication activity.",
        contributing_factors=["Repeated failed SSH logins"],
        evidence=["Wazuh recorded repeated failed SSH logins."],
        operational_impact="Potential unauthorized access risk.",
        recommended_investigation=["Review the affected account and source address."],
        confidence="medium",
        warnings=[],
    ).model_dump_json()


def test_ollama_provider_uses_summary_model_and_structured_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert str(request.url) == "http://127.0.0.1:11434/api/generate"
        assert payload["model"] == "gemma3:1b-it-qat"
        assert payload["stream"] is False
        assert payload["think"] is False
        assert payload["keep_alive"] == 0
        assert payload["options"] == {
            "num_ctx": 1024,
            "num_predict": 256,
            "temperature": 0,
        }
        assert payload["format"]["type"] == "object"
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "response": valid_analysis_json(),
                "done": True,
                "done_reason": "stop",
            },
        )

    async def run() -> None:
        provider = OllamaProvider(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        result = await provider.generate(
            purpose="summary",
            system_prompt="Use only supplied evidence.",
            prompt="Synthetic monitoring evidence.",
        )

        assert result.confidence == "medium"
        assert result.summary.startswith("Two authentication")

    import asyncio

    asyncio.run(run())


def test_ollama_provider_uses_minimal_investigation_schema() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3:1.7b"
        assert set(payload["format"]["properties"]) == {
            "likely_explanation",
            "recommended_investigation",
            "confidence",
        }
        assert "summary" not in payload["format"]["properties"]
        assert "evidence" not in payload["format"]["properties"]
        response = {
            "likely_explanation": "The evidence indicates multiple items require review.",
            "recommended_investigation": ["Review the selected monitoring evidence."],
            "confidence": "medium",
        }
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "response": json.dumps(response),
                "done": True,
                "done_reason": "stop",
            },
        )

    async def run() -> None:
        provider = OllamaProvider(make_settings(), transport=httpx.MockTransport(handler))
        result = await provider.generate_investigation(
            system_prompt="Use only supplied evidence.",
            prompt="Synthetic monitoring evidence.",
        )
        assert result.confidence == "medium"

    import asyncio

    asyncio.run(run())


def test_ollama_provider_rejects_invalid_or_truncated_model_output() -> None:
    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "model": "gemma3:1b-it-qat",
                    "response": "{not-json}",
                    "done": True,
                    "done_reason": "stop",
                },
            ),
            httpx.Response(
                200,
                json={
                    "model": "gemma3:1b-it-qat",
                    "response": valid_analysis_json(),
                    "done": True,
                    "done_reason": "length",
                },
            ),
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    async def run() -> None:
        provider = OllamaProvider(make_settings(), transport=httpx.MockTransport(handler))
        for _ in range(2):
            with pytest.raises(AIError) as exc_info:
                await provider.generate(
                    purpose="summary",
                    system_prompt="Use only supplied evidence.",
                    prompt="Synthetic monitoring evidence.",
                )
            assert exc_info.value.code == "AI_BAD_RESPONSE"

    import asyncio

    asyncio.run(run())


def test_ollama_provider_maps_runtime_model_and_timeout_failures() -> None:
    async def unavailable_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async def missing_model_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow model", request=request)

    async def run() -> None:
        cases = [
            (unavailable_handler, "AI_RUNTIME_UNAVAILABLE"),
            (missing_model_handler, "AI_MODEL_UNAVAILABLE"),
            (timeout_handler, "AI_TIMEOUT"),
        ]
        for handler, expected_code in cases:
            provider = OllamaProvider(make_settings(), transport=httpx.MockTransport(handler))
            with pytest.raises(AIError) as exc_info:
                await provider.generate(
                    purpose="summary",
                    system_prompt="Use only supplied evidence.",
                    prompt="Synthetic monitoring evidence.",
                )
            assert exc_info.value.code == expected_code

    import asyncio

    asyncio.run(run())


def test_ollama_provider_rejects_requests_when_ai_is_disabled() -> None:
    async def run() -> None:
        provider = OllamaProvider(make_settings(ai_enabled=False))
        with pytest.raises(AIError) as exc_info:
            await provider.generate(
                purpose="summary",
                system_prompt="Use only supplied evidence.",
                prompt="Synthetic monitoring evidence.",
            )
        assert exc_info.value.code == "AI_DISABLED"

    import asyncio

    asyncio.run(run())

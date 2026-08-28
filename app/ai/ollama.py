from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.errors import AIError
from app.ai.models import (
    AIAnalysis,
    AIInvestigationModelOutput,
    AIModelReadiness,
    AIPurpose,
    AIReadinessResponse,
)
from app.core.config import Settings
from app.core.http import create_http_client


StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


class OllamaProvider:
    """Local-only Ollama provider with bounded generation and strict output validation."""

    _READINESS_TIMEOUT_SECONDS = 3.0

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def readiness(self) -> AIReadinessResponse:
        """Check local runtime/model readiness without generating content or exposing details."""

        summary = AIModelReadiness(
            model=self._settings.ai_summary_model,
            available=None,
        )
        investigation = AIModelReadiness(
            model=self._settings.ai_investigation_model,
            available=None,
        )
        if not self._settings.ai_enabled:
            return AIReadinessResponse(
                enabled=False,
                status="disabled",
                runtime_reachable=None,
                summary_model=summary,
                investigation_model=investigation,
            )

        base_url = str(self._settings.ai_ollama_base_url).rstrip("/")
        try:
            async with create_http_client(
                timeout_seconds=min(
                    float(self._settings.ai_timeout_seconds),
                    self._READINESS_TIMEOUT_SECONDS,
                ),
                transport=self._transport,
            ) as client:
                response = await client.get(f"{base_url}/api/tags")
        except (httpx.TimeoutException, httpx.RequestError):
            return AIReadinessResponse(
                enabled=True,
                status="runtime_unavailable",
                runtime_reachable=False,
                summary_model=summary,
                investigation_model=investigation,
            )

        if not response.is_success:
            return AIReadinessResponse(
                enabled=True,
                status="runtime_unavailable",
                runtime_reachable=False,
                summary_model=summary,
                investigation_model=investigation,
            )

        try:
            body = response.json()
        except ValueError:
            body = None
        models = body.get("models") if isinstance(body, dict) else None
        if not isinstance(models, list):
            return AIReadinessResponse(
                enabled=True,
                status="runtime_unavailable",
                runtime_reachable=False,
                summary_model=summary,
                investigation_model=investigation,
            )

        installed: set[str] = set()
        for item in models:
            if not isinstance(item, dict):
                continue
            for key in ("name", "model"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    installed.add(value)

        summary = summary.model_copy(
            update={"available": self._settings.ai_summary_model in installed}
        )
        investigation = investigation.model_copy(
            update={"available": self._settings.ai_investigation_model in installed}
        )
        ready = summary.available is True and investigation.available is True
        return AIReadinessResponse(
            enabled=True,
            status="ready" if ready else "model_unavailable",
            runtime_reachable=True,
            summary_model=summary,
            investigation_model=investigation,
        )

    async def generate(
        self,
        *,
        purpose: AIPurpose,
        system_prompt: str,
        prompt: str,
    ) -> AIAnalysis:
        model = (
            self._settings.ai_summary_model
            if purpose == "summary"
            else self._settings.ai_investigation_model
        )
        return await self._generate_structured(
            model=model,
            system_prompt=system_prompt,
            prompt=prompt,
            schema=AIAnalysis,
        )

    async def generate_investigation(
        self,
        *,
        system_prompt: str,
        prompt: str,
    ) -> AIInvestigationModelOutput:
        return await self._generate_structured(
            model=self._settings.ai_investigation_model,
            system_prompt=system_prompt,
            prompt=prompt,
            schema=AIInvestigationModelOutput,
        )

    async def _generate_structured(
        self,
        *,
        model: str,
        system_prompt: str,
        prompt: str,
        schema: type[StructuredResponseT],
    ) -> StructuredResponseT:
        if not self._settings.ai_enabled:
            raise AIError(code="AI_DISABLED", retryable=False)

        base_url = str(self._settings.ai_ollama_base_url).rstrip("/")
        payload = {
            "model": model,
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": schema.model_json_schema(),
            "keep_alive": self._settings.ai_keep_alive_seconds,
            "options": {
                "num_ctx": self._settings.ai_context_size,
                "num_predict": self._settings.ai_max_output_tokens,
                "temperature": 0,
            },
        }
        try:
            async with create_http_client(
                timeout_seconds=self._settings.ai_timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(f"{base_url}/api/generate", json=payload)
        except httpx.TimeoutException as exc:
            raise AIError(code="AI_TIMEOUT", retryable=True) from exc
        except httpx.RequestError as exc:
            raise AIError(code="AI_RUNTIME_UNAVAILABLE", retryable=True) from exc

        if response.status_code == 404:
            raise AIError(code="AI_MODEL_UNAVAILABLE", retryable=False)
        if response.status_code >= 500:
            raise AIError(code="AI_RUNTIME_UNAVAILABLE", retryable=True)
        if not response.is_success:
            raise AIError(code="AI_BAD_RESPONSE", retryable=False)
        try:
            body = response.json()
        except ValueError as exc:
            raise AIError(code="AI_BAD_RESPONSE", retryable=False) from exc
        if body.get("done") is not True or body.get("done_reason") == "length":
            raise AIError(code="AI_BAD_RESPONSE", retryable=False)
        model_output = body.get("response")
        if not isinstance(model_output, str) or not model_output.strip():
            raise AIError(code="AI_BAD_RESPONSE", retryable=False)
        try:
            return schema.model_validate_json(model_output)
        except ValidationError as exc:
            raise AIError(code="AI_BAD_RESPONSE", retryable=False) from exc

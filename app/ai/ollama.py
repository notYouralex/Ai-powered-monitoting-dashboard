import httpx
from pydantic import ValidationError

from app.ai.errors import AIError
from app.ai.models import AIAnalysis, AIInvestigationModelOutput, AIPurpose
from app.core.config import Settings
from app.core.http import create_http_client


class OllamaProvider:
    """Local-only Ollama provider with bounded generation and strict output validation."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def generate(
        self,
        *,
        purpose: AIPurpose,
        system_prompt: str,
        prompt: str,
    ) -> AIAnalysis:
        if not self._settings.ai_enabled:
            raise AIError(code="AI_DISABLED", retryable=False)

        model = (
            self._settings.ai_summary_model
            if purpose == "summary"
            else self._settings.ai_investigation_model
        )
        base_url = str(self._settings.ai_ollama_base_url).rstrip("/")
        payload = {
            "model": model,
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": AIAnalysis.model_json_schema(),
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
            return AIAnalysis.model_validate_json(model_output)
        except ValidationError as exc:
            raise AIError(code="AI_BAD_RESPONSE", retryable=False) from exc

    async def generate_investigation(
        self,
        *,
        system_prompt: str,
        prompt: str,
    ) -> AIInvestigationModelOutput:
        if not self._settings.ai_enabled:
            raise AIError(code="AI_DISABLED", retryable=False)

        return await self._generate_structured(
            model=self._settings.ai_investigation_model,
            system_prompt=system_prompt,
            prompt=prompt,
            schema=AIInvestigationModelOutput,
        )

    async def _generate_structured(self, *, model, system_prompt, prompt, schema):
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

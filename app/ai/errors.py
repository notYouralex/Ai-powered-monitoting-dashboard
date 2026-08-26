from typing import Literal, TypeAlias

from fastapi import Request
from fastapi.responses import JSONResponse


AIErrorCode: TypeAlias = Literal[
    "AI_DISABLED",
    "AI_RUNTIME_UNAVAILABLE",
    "AI_MODEL_UNAVAILABLE",
    "AI_TIMEOUT",
    "AI_BAD_RESPONSE",
]

_STATUS_BY_CODE: dict[AIErrorCode, int] = {
    "AI_DISABLED": 503,
    "AI_RUNTIME_UNAVAILABLE": 503,
    "AI_MODEL_UNAVAILABLE": 503,
    "AI_TIMEOUT": 504,
    "AI_BAD_RESPONSE": 502,
}

_MESSAGE_BY_CODE: dict[AIErrorCode, str] = {
    "AI_DISABLED": "AI analysis is disabled.",
    "AI_RUNTIME_UNAVAILABLE": "AI analysis is temporarily unavailable.",
    "AI_MODEL_UNAVAILABLE": "The configured local AI model is unavailable.",
    "AI_TIMEOUT": "AI analysis exceeded the allowed response time.",
    "AI_BAD_RESPONSE": "AI analysis returned an unusable response.",
}


class AIError(Exception):
    """Safe local-AI failure that does not expose model/runtime response content."""

    def __init__(self, *, code: AIErrorCode, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def ai_error_handler(request: Request, exc: AIError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=_STATUS_BY_CODE[exc.code],
        content={
            "error": {
                "code": exc.code,
                "message": _MESSAGE_BY_CODE[exc.code],
                "retryable": exc.retryable,
                "request_id": request_id,
            }
        },
    )

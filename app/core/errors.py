from typing import Literal

from fastapi import Request
from fastapi.responses import JSONResponse

from app.contracts import IntegrationSource


IntegrationErrorCode = Literal[
    "SOURCE_NOT_CONFIGURED",
    "SOURCE_AUTH_FAILED",
    "SOURCE_UNAVAILABLE",
    "SOURCE_RATE_LIMITED",
    "SOURCE_BAD_RESPONSE",
]

_STATUS_BY_CODE: dict[IntegrationErrorCode, int] = {
    "SOURCE_NOT_CONFIGURED": 503,
    "SOURCE_AUTH_FAILED": 502,
    "SOURCE_UNAVAILABLE": 503,
    "SOURCE_RATE_LIMITED": 503,
    "SOURCE_BAD_RESPONSE": 502,
}

_SOURCE_NAMES: dict[IntegrationSource, str] = {
    "wazuh": "Wazuh",
    "zabbix": "Zabbix",
    "snipe_it": "Snipe-IT",
    "freshservice": "Freshservice",
}

_MESSAGE_BY_CODE: dict[IntegrationErrorCode, str] = {
    "SOURCE_NOT_CONFIGURED": "{source} is not configured.",
    "SOURCE_AUTH_FAILED": "{source} authentication failed.",
    "SOURCE_UNAVAILABLE": "{source} is temporarily unavailable.",
    "SOURCE_RATE_LIMITED": "{source} is temporarily rate limited.",
    "SOURCE_BAD_RESPONSE": "{source} returned an unusable response.",
}


class IntegrationError(Exception):
    def __init__(
        self,
        *,
        source: IntegrationSource,
        code: IntegrationErrorCode,
        retryable: bool,
    ) -> None:
        super().__init__(code)
        self.source = source
        self.code = code
        self.retryable = retryable


def integration_error_handler(request: Request, exc: IntegrationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    message = _MESSAGE_BY_CODE[exc.code].format(source=_SOURCE_NAMES[exc.source])
    return JSONResponse(
        status_code=_STATUS_BY_CODE[exc.code],
        content={
            "error": {
                "code": exc.code,
                "message": message,
                "source": exc.source,
                "retryable": exc.retryable,
                "request_id": request_id,
            }
        },
    )

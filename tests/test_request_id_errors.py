import re

import pytest
from fastapi.testclient import TestClient

from app.core.errors import IntegrationError
from app.main import create_app

UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


def test_response_gets_generated_request_id() -> None:
    response = TestClient(create_app()).get("/health")

    assert UUID_HEX.fullmatch(response.headers["X-Request-ID"])


def test_valid_incoming_request_id_is_preserved() -> None:
    response = TestClient(create_app()).get(
        "/health",
        headers={"X-Request-ID": "dashboard-check_01"},
    )

    assert response.headers["X-Request-ID"] == "dashboard-check_01"


@pytest.mark.parametrize(
    "value",
    ["", "contains space", "bad:value", "x" * 65],
)
def test_invalid_incoming_request_id_is_replaced(value: str) -> None:
    response = TestClient(create_app()).get(
        "/health",
        headers={"X-Request-ID": value},
    )

    assert response.headers["X-Request-ID"] != value
    assert UUID_HEX.fullmatch(response.headers["X-Request-ID"])


def test_integration_error_uses_safe_envelope_and_request_id() -> None:
    app = create_app()

    @app.get("/_test/source-error")
    def source_error():
        raise IntegrationError(
            source="wazuh",
            code="SOURCE_UNAVAILABLE",
            retryable=True,
        )

    response = TestClient(app).get(
        "/_test/source-error",
        headers={"X-Request-ID": "req-123"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "SOURCE_UNAVAILABLE",
            "message": "Wazuh is temporarily unavailable.",
            "source": "wazuh",
            "retryable": True,
            "request_id": "req-123",
        }
    }
    assert response.headers["X-Request-ID"] == "req-123"


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        ("SOURCE_NOT_CONFIGURED", 503),
        ("SOURCE_AUTH_FAILED", 502),
        ("SOURCE_UNAVAILABLE", 503),
        ("SOURCE_RATE_LIMITED", 503),
        ("SOURCE_BAD_RESPONSE", 502),
    ],
)
def test_integration_error_code_status_mapping(code: str, expected_status: int) -> None:
    app = create_app()

    @app.get("/_test/mapped-error")
    def mapped_error():
        raise IntegrationError(source="zabbix", code=code, retryable=False)

    response = TestClient(app).get("/_test/mapped-error")

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == code


def test_integration_error_does_not_expose_chained_exception() -> None:
    fake_secret = "fake-private-token-123456789"
    app = create_app()

    @app.get("/_test/secret-error")
    def secret_error():
        try:
            raise RuntimeError(fake_secret)
        except RuntimeError as exc:
            raise IntegrationError(
                source="zabbix",
                code="SOURCE_BAD_RESPONSE",
                retryable=False,
            ) from exc

    response = TestClient(app).get("/_test/secret-error")

    assert response.status_code == 502
    assert fake_secret not in response.text
    assert "RuntimeError" not in response.text

from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.low_level import Type
from pydantic import SecretStr

from app.ai.errors import AIError
from app.ai.models import (
    AIAnalysis,
    AIDashboardSummaryResponse,
    AIInvestigationResponse,
    AIModelReadiness,
    AIQuestionClassification,
    AIQueryResponse,
    AIReadinessResponse,
)
from app.ai.cache import AIExecutiveSummaryCache
from app.ai.router import (
    get_ai_dashboard_summary_cache,
    get_ai_investigation_service,
    get_ai_readiness_provider,
    get_ai_service,
    get_ai_summary_cache,
)
from app.db.models import User


NOW = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
START = NOW - timedelta(hours=24)


def make_response(start: datetime = START, end: datetime = NOW) -> AIQueryResponse:
    return AIQueryResponse(
        observed_at=NOW,
        range_start=start,
        range_end=end,
        analysis=AIAnalysis(
            summary="Environment summary.",
            confidence="medium",
        ),
        source_warnings=[],
    )


def login(auth_env) -> None:
    with auth_env.session_factory() as db:
        db.add(
            User(
                username="alice",
                password_hash=PasswordHasher(type=Type.ID).hash("correct horse"),
                is_active=True,
                is_admin=False,
            )
        )
        db.commit()

    response = auth_env.client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "correct horse"},
    )
    assert response.status_code == 200


class FakeAIService:
    def __init__(self, *, error: AIError | None = None) -> None:
        self.error = error
        self.summary_calls = []
        self.dashboard_summary_calls = []
        self.source_summary_calls = []
        self.investigation_calls = []

    async def summarize_executive(self, start, end) -> AIQueryResponse:
        self.summary_calls.append((start, end))
        if self.error is not None:
            raise self.error
        return make_response(start, end)

    async def summarize_dashboard(self, start, end) -> AIDashboardSummaryResponse:
        self.dashboard_summary_calls.append((start, end))
        if self.error is not None:
            raise self.error
        analysis = AIAnalysis(summary="Dashboard summary.", confidence="medium")
        return AIDashboardSummaryResponse(
            observed_at=end,
            range_start=start,
            range_end=end,
            executive=analysis,
            wazuh=analysis,
            zabbix=analysis,
            snipe_it=analysis,
            freshservice=analysis,
        )

    async def summarize_source(self, start, end, *, source) -> AIQueryResponse:
        self.source_summary_calls.append((source, start, end))
        if self.error is not None:
            raise self.error
        return make_response(start, end)

    async def investigate(self, question, start, end) -> AIInvestigationResponse:
        self.investigation_calls.append((question, start, end))
        if self.error is not None:
            raise self.error
        return AIInvestigationResponse(
            observed_at=end,
            range_start=start,
            range_end=end,
            classification=AIQuestionClassification(scope="environment"),
            analysis=AIAnalysis(summary="Investigation result.", confidence="medium"),
            source_warnings=[],
        )


class FakeAIReadinessProvider:
    def __init__(self, response: AIReadinessResponse) -> None:
        self.response = response
        self.calls = 0

    async def readiness(self) -> AIReadinessResponse:
        self.calls += 1
        return self.response


def ready_response() -> AIReadinessResponse:
    return AIReadinessResponse(
        enabled=True,
        status="ready",
        runtime_reachable=True,
        summary_model=AIModelReadiness(
            model="gemma3:1b-it-qat",
            available=True,
        ),
        investigation_model=AIModelReadiness(
            model="qwen3:1.7b",
            available=True,
        ),
    )


def test_ai_status_requires_dashboard_access(auth_env) -> None:
    response = auth_env.client.get("/api/ai/status")

    assert response.status_code == 401


def test_ai_status_returns_disabled_contract_for_signed_in_user(auth_env) -> None:
    login(auth_env)
    auth_env.settings.ai_enabled = False

    response = auth_env.client.get("/api/ai/status")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["status"] == "disabled"
    assert body["runtime_reachable"] is None
    assert body["summary_model"] == {
        "model": auth_env.settings.ai_summary_model,
        "available": None,
    }
    assert body["investigation_model"] == {
        "model": auth_env.settings.ai_investigation_model,
        "available": None,
    }


def test_ai_status_returns_provider_readiness_for_dashboard_access(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    provider = FakeAIReadinessProvider(ready_response())
    auth_env.client.app.dependency_overrides[get_ai_readiness_provider] = lambda: provider

    response = auth_env.client.get(
        "/api/ai/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == ready_response().model_dump(mode="json")
    assert provider.calls == 1


def test_interactive_ai_query_requires_authenticated_user(auth_env) -> None:
    auth_env.settings.ai_enabled = True

    response = auth_env.client.post(
        "/api/ai/query",
        json={"question": "What needs attention?"},
    )

    assert response.status_code == 401


def test_interactive_ai_query_rejects_grafana_service_token(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    auth_env.settings.ai_enabled = True

    response = auth_env.client.post(
        "/api/ai/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "What needs attention?"},
    )

    assert response.status_code == 401


def test_interactive_ai_query_uses_bounded_request_and_time_range(auth_env) -> None:
    auth_env.settings.ai_enabled = True
    login(auth_env)
    fake_service = FakeAIService()
    auth_env.client.app.dependency_overrides[get_ai_investigation_service] = lambda: fake_service

    response = auth_env.client.post(
        "/api/ai/query",
        params={"from": START.isoformat(), "to": NOW.isoformat()},
        json={"question": "  What needs attention?  "},
    )

    assert response.status_code == 200
    assert fake_service.investigation_calls == [("What needs attention?", START, NOW)]
    body = response.json()
    assert body["classification"]["scope"] == "environment"
    assert body["analysis"]["summary"] == "Investigation result."


def test_interactive_ai_query_is_disabled_before_service(auth_env) -> None:
    login(auth_env)
    fake_service = FakeAIService()
    auth_env.client.app.dependency_overrides[get_ai_investigation_service] = lambda: fake_service

    response = auth_env.client.post(
        "/api/ai/query",
        json={"question": "What needs attention?"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_DISABLED"
    assert fake_service.investigation_calls == []


def test_interactive_ai_query_rejects_invalid_time_range(auth_env) -> None:
    auth_env.settings.ai_enabled = True
    login(auth_env)
    fake_service = FakeAIService()
    auth_env.client.app.dependency_overrides[get_ai_investigation_service] = lambda: fake_service

    response = auth_env.client.post(
        "/api/ai/query",
        params={
            "from": START.isoformat(),
            "to": (START + timedelta(days=31)).isoformat(),
        },
        json={"question": "What needs attention?"},
    )

    assert response.status_code == 422
    assert fake_service.investigation_calls == []


def test_ai_executive_insight_caches_only_exact_requested_range(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    auth_env.settings.ai_enabled = True
    auth_env.settings.ai_summary_cache_seconds = 300
    fake_service = FakeAIService()
    cache = AIExecutiveSummaryCache[AIQueryResponse](clock=lambda: 100.0)
    auth_env.client.app.dependency_overrides[get_ai_service] = lambda: fake_service
    auth_env.client.app.dependency_overrides[get_ai_summary_cache] = lambda: cache

    for offset_seconds in (0, 30):
        response = auth_env.client.get(
            "/api/ai/insights/executive",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "from": (START + timedelta(seconds=offset_seconds)).isoformat(),
                "to": (NOW + timedelta(seconds=offset_seconds)).isoformat(),
            },
        )
        assert response.status_code == 200
        assert response.json()["range_start"] == (
            START + timedelta(seconds=offset_seconds)
        ).isoformat().replace("+00:00", "Z")
        assert response.json()["range_end"] == (
            NOW + timedelta(seconds=offset_seconds)
        ).isoformat().replace("+00:00", "Z")

    assert fake_service.summary_calls == [
        (START, NOW),
        (START + timedelta(seconds=30), NOW + timedelta(seconds=30)),
    ]


def test_ai_dashboard_summary_cache_keeps_requested_range_exact(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    auth_env.settings.ai_enabled = True
    auth_env.settings.ai_summary_cache_seconds = 300
    fake_service = FakeAIService()
    cache = AIExecutiveSummaryCache[AIDashboardSummaryResponse](clock=lambda: 100.0)
    auth_env.client.app.dependency_overrides[get_ai_service] = lambda: fake_service
    auth_env.client.app.dependency_overrides[get_ai_dashboard_summary_cache] = lambda: cache

    for offset_seconds in (0, 30):
        response = auth_env.client.get(
            "/api/ai/insights/dashboard",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "from": (START + timedelta(seconds=offset_seconds)).isoformat(),
                "to": (NOW + timedelta(seconds=offset_seconds)).isoformat(),
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body) >= {
            "executive",
            "wazuh",
            "zabbix",
            "snipe_it",
            "freshservice",
        }
        assert body["range_start"] == (
            START + timedelta(seconds=offset_seconds)
        ).isoformat().replace("+00:00", "Z")
        assert body["range_end"] == (
            NOW + timedelta(seconds=offset_seconds)
        ).isoformat().replace("+00:00", "Z")

    assert fake_service.dashboard_summary_calls == [
        (START, NOW),
        (START + timedelta(seconds=30), NOW + timedelta(seconds=30)),
    ]


def test_ai_source_insights_use_independent_caches(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    auth_env.settings.ai_enabled = True
    auth_env.settings.ai_summary_cache_seconds = 300
    fake_service = FakeAIService()
    auth_env.client.app.dependency_overrides[get_ai_service] = lambda: fake_service

    for route in ("wazuh", "zabbix", "snipe-it", "freshservice"):
        for offset_seconds in (0, 30):
            response = auth_env.client.get(
                f"/api/ai/insights/{route}",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "from": (START + timedelta(seconds=offset_seconds)).isoformat(),
                    "to": (NOW + timedelta(seconds=offset_seconds)).isoformat(),
                },
            )
            assert response.status_code == 200

    assert fake_service.source_summary_calls == [
        ("wazuh", START, NOW),
        ("wazuh", START + timedelta(seconds=30), NOW + timedelta(seconds=30)),
        ("zabbix", START, NOW),
        ("zabbix", START + timedelta(seconds=30), NOW + timedelta(seconds=30)),
        ("snipe_it", START, NOW),
        ("snipe_it", START + timedelta(seconds=30), NOW + timedelta(seconds=30)),
        ("freshservice", START, NOW),
        ("freshservice", START + timedelta(seconds=30), NOW + timedelta(seconds=30)),
    ]


def test_ai_executive_insight_is_disabled_before_cache_or_service(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    fake_service = FakeAIService()
    cache = AIExecutiveSummaryCache(clock=lambda: 100.0)
    auth_env.client.app.dependency_overrides[get_ai_service] = lambda: fake_service
    auth_env.client.app.dependency_overrides[get_ai_summary_cache] = lambda: cache

    response = auth_env.client.get(
        "/api/ai/insights/executive",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_DISABLED"
    assert fake_service.summary_calls == []


def test_ai_source_insights_are_disabled_before_cache_or_service(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    fake_service = FakeAIService()
    auth_env.client.app.dependency_overrides[get_ai_service] = lambda: fake_service

    for route in ("wazuh", "zabbix", "snipe-it", "freshservice"):
        response = auth_env.client.get(
            f"/api/ai/insights/{route}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "AI_DISABLED"

    assert fake_service.source_summary_calls == []


def test_ai_errors_are_returned_without_runtime_details(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    auth_env.settings.ai_enabled = True
    fake_service = FakeAIService(
        error=AIError(code="AI_RUNTIME_UNAVAILABLE", retryable=True)
    )
    auth_env.client.app.dependency_overrides[get_ai_service] = lambda: fake_service

    response = auth_env.client.get(
        "/api/ai/insights/executive",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "AI_RUNTIME_UNAVAILABLE"
    assert body["retryable"] is True
    assert "ollama" not in body["message"].lower()
    assert "connection" not in body["message"].lower()

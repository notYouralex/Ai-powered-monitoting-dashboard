from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from pydantic import SecretStr

from app.contracts import IntegrationHealthSummary
from app.db.models import SyncRun, User, ZabbixDashboardCache
from app.integrations.zabbix import router as zabbix_router_module
from app.integrations.zabbix.models import (
    ZabbixDashboardResponse,
    ZabbixDashboardSummary,
    ZabbixDiskPressure,
    ZabbixProblem,
    ZabbixProblemHost,
    ZabbixResourcePressure,
    ZabbixResourceTrend,
    ZabbixResourceTrendPoint,
    ZabbixTopAffectedHost,
)
from app.main import create_app


NOW = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)


def create_user(auth_env) -> None:
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


def login(auth_env) -> None:
    response = auth_env.client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "correct horse"},
    )
    assert response.status_code == 200


class FakeDashboardService:
    def __init__(self) -> None:
        self.calls = 0

    def get_dashboard(self) -> ZabbixDashboardResponse:
        self.calls += 1
        return ZabbixDashboardResponse(
            observed_at=NOW,
            health=IntegrationHealthSummary(
                source="zabbix",
                status="healthy",
                observed_at=NOW,
                last_success_at=NOW,
                response_time_ms=1,
            ),
            summary=ZabbixDashboardSummary(
                hosts_total=0,
                hosts_enabled=0,
                hosts_disabled=0,
                hosts_in_maintenance=0,
                interfaces_available=0,
                interfaces_unavailable=0,
                interfaces_unknown=0,
                problems_total=1,
                problems_not_classified=0,
                problems_information=0,
                problems_warning=0,
                problems_average=0,
                problems_high=1,
                problems_disaster=0,
                problems_unknown=0,
                problems_unacknowledged=1,
                problems_suppressed=0,
                resource_hosts_total=1,
                resource_hosts_with_cpu=1,
                resource_hosts_with_memory=1,
                resource_hosts_with_disk=1,
            ),
            active_problems=[
                ZabbixProblem(
                    event_id="7001",
                    trigger_id="9001",
                    name="CPU load is high",
                    severity="high",
                    started_at=NOW,
                    acknowledged=False,
                    suppressed=False,
                    hosts=[
                        ZabbixProblemHost(
                            host_id="10001",
                            technical_name="web-01.internal",
                            name="Web 01",
                        )
                    ],
                )
            ],
            resource_pressure=[
                ZabbixResourcePressure(
                    host_id="10001",
                    cpu_used_percent=75.0,
                    cpu_observed_at=NOW,
                    memory_used_percent=60.0,
                    memory_observed_at=NOW,
                    disks=[
                        ZabbixDiskPressure(
                            filesystem="/",
                            used_percent=70.0,
                            observed_at=NOW,
                        )
                    ],
                )
            ],
            top_affected_hosts=[
                ZabbixTopAffectedHost(
                    host_id="10001",
                    technical_name="web-01.internal",
                    name="Web 01",
                    highest_problem_severity="high",
                    active_problem_count=1,
                    unavailable_interface_count=2,
                    peak_resource_percent=92.0,
                    peak_resource="disk",
                    peak_filesystem="/var",
                )
            ],
            resource_trends=[
                ZabbixResourceTrend(
                    host_id="10001",
                    metric="cpu",
                    points=[
                        ZabbixResourceTrendPoint(
                            observed_at=datetime(2026, 8, 13, 2, 0, tzinfo=timezone.utc),
                            average_used_percent=55.0,
                        ),
                        ZabbixResourceTrendPoint(
                            observed_at=datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc),
                            average_used_percent=65.0,
                        ),
                    ],
                ),
                ZabbixResourceTrend(
                    host_id="10001",
                    metric="disk",
                    filesystem="/var",
                    points=[
                        ZabbixResourceTrendPoint(
                            observed_at=datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc),
                            average_used_percent=88.0,
                        )
                    ],
                ),
            ],
        )


def test_zabbix_dashboard_requires_authentication(auth_env) -> None:
    response = auth_env.client.get("/api/dashboard/zabbix")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_zabbix_dashboard_accepts_configured_grafana_api_token(auth_env) -> None:
    auth_env.settings.grafana_api_token = SecretStr("g" * 48)
    dependency = getattr(zabbix_router_module, "get_zabbix_dashboard_service", None)
    assert dependency is not None
    fake_service = FakeDashboardService()
    auth_env.client.app.dependency_overrides[dependency] = lambda: fake_service

    response = auth_env.client.get(
        "/api/dashboard/zabbix",
        headers={"Authorization": f"Bearer {'g' * 48}"},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "zabbix"
    assert fake_service.calls == 1


def test_zabbix_dashboard_rejects_invalid_grafana_api_token(auth_env) -> None:
    auth_env.settings.grafana_api_token = SecretStr("g" * 48)

    response = auth_env.client.get(
        "/api/dashboard/zabbix",
        headers={"Authorization": f"Bearer {'x' * 48}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_grafana_api_token_does_not_authenticate_user_endpoints(auth_env) -> None:
    auth_env.settings.grafana_api_token = SecretStr("g" * 48)

    response = auth_env.client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {'g' * 48}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_invalid_bearer_header_does_not_fall_back_to_valid_session(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)
    auth_env.settings.grafana_api_token = SecretStr("g" * 48)

    response = auth_env.client.get(
        "/api/dashboard/zabbix",
        headers={"Authorization": "Basic not-a-service-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_authenticated_unconfigured_zabbix_returns_safe_source_error(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)

    response = auth_env.client.get("/api/dashboard/zabbix")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "SOURCE_NOT_CONFIGURED"
    assert body["error"]["source"] == "zabbix"
    assert body["error"]["retryable"] is False
    assert body["error"]["request_id"]
    assert response.headers["X-Request-ID"] == body["error"]["request_id"]


def test_authenticated_zabbix_dashboard_returns_normalized_response(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)
    dependency = getattr(zabbix_router_module, "get_zabbix_dashboard_service", None)
    assert dependency is not None
    fake_service = FakeDashboardService()
    auth_env.client.app.dependency_overrides[dependency] = lambda: fake_service

    response = auth_env.client.get("/api/dashboard/zabbix")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "zabbix"
    assert body["health"]["status"] == "healthy"
    assert body["summary"]["hosts_total"] == 0
    assert body["summary"]["problems_total"] == 1
    assert body["summary"]["problems_high"] == 1
    assert body["summary"]["problems_unacknowledged"] == 1
    assert body["active_problems"][0]["event_id"] == "7001"
    assert body["active_problems"][0]["severity"] == "high"
    assert body["active_problems"][0]["hosts"][0]["host_id"] == "10001"
    assert body["summary"]["resource_hosts_total"] == 1
    assert body["summary"]["resource_hosts_with_cpu"] == 1
    assert body["summary"]["resource_hosts_with_memory"] == 1
    assert body["summary"]["resource_hosts_with_disk"] == 1
    assert body["resource_pressure"][0]["host_id"] == "10001"
    assert body["resource_pressure"][0]["cpu_used_percent"] == 75.0
    assert body["resource_pressure"][0]["memory_used_percent"] == 60.0
    assert body["resource_pressure"][0]["cpu_observed_at"] == "2026-08-13T04:00:00Z"
    assert body["resource_pressure"][0]["disks"][0]["filesystem"] == "/"
    assert body["resource_pressure"][0]["disks"][0]["used_percent"] == 70.0
    assert body["top_affected_hosts"][0]["host_id"] == "10001"
    assert body["top_affected_hosts"][0]["technical_name"] == "web-01.internal"
    assert body["top_affected_hosts"][0]["name"] == "Web 01"
    assert body["top_affected_hosts"][0]["highest_problem_severity"] == "high"
    assert body["top_affected_hosts"][0]["active_problem_count"] == 1
    assert body["top_affected_hosts"][0]["unavailable_interface_count"] == 2
    assert body["top_affected_hosts"][0]["peak_resource_percent"] == 92.0
    assert body["top_affected_hosts"][0]["peak_resource"] == "disk"
    assert body["top_affected_hosts"][0]["peak_filesystem"] == "/var"
    assert body["resource_trends"][0]["host_id"] == "10001"
    assert body["resource_trends"][0]["metric"] == "cpu"
    assert body["resource_trends"][0]["filesystem"] is None
    assert body["resource_trends"][0]["points"][0]["observed_at"] == "2026-08-13T02:00:00Z"
    assert body["resource_trends"][0]["points"][0]["average_used_percent"] == 55.0
    assert body["resource_trends"][0]["points"][1]["observed_at"] == "2026-08-13T03:00:00Z"
    assert body["resource_trends"][0]["points"][1]["average_used_percent"] == 65.0
    assert body["resource_trends"][1]["host_id"] == "10001"
    assert body["resource_trends"][1]["metric"] == "disk"
    assert body["resource_trends"][1]["filesystem"] == "/var"
    assert body["resource_trends"][1]["points"][0]["average_used_percent"] == 88.0
    assert fake_service.calls == 1


def test_authenticated_zabbix_dashboard_reads_cached_snapshot_after_failed_refresh(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)
    refreshed_at = datetime.now(timezone.utc)
    snapshot = FakeDashboardService().get_dashboard().model_dump(mode="json")

    with auth_env.session_factory() as db:
        db.add(
            ZabbixDashboardCache(
                id=1,
                snapshot=snapshot,
                refreshed_at=refreshed_at,
            )
        )
        db.add_all(
            [
                SyncRun(
                    source="zabbix",
                    sync_type="snapshot",
                    status="success",
                    started_at=refreshed_at - timedelta(seconds=1),
                    completed_at=refreshed_at,
                    records_received=1,
                    records_upserted=1,
                ),
                SyncRun(
                    source="zabbix",
                    sync_type="snapshot",
                    status="failed",
                    started_at=refreshed_at + timedelta(milliseconds=1),
                    completed_at=refreshed_at + timedelta(milliseconds=2),
                    records_received=0,
                    records_upserted=0,
                    error_code="SOURCE_UNAVAILABLE",
                ),
            ]
        )
        db.commit()

    auth_env.settings.zabbix_base_url = "http://127.0.0.1:1/api_jsonrpc.php"
    auth_env.settings.zabbix_api_token = SecretStr("test-token")
    auth_env.settings.zabbix_timeout_seconds = 1

    response = auth_env.client.get("/api/dashboard/zabbix")

    assert response.status_code == 200
    body = response.json()
    warning = "The latest Zabbix refresh failed; showing last successful cached data."
    assert body["is_stale"] is True
    assert body["health"]["status"] == "degraded"
    assert body["health"]["is_stale"] is True
    assert body["health"]["last_success_at"] == refreshed_at.isoformat().replace("+00:00", "Z")
    assert warning in body["health"]["warnings"]
    assert warning in body["warnings"]
    assert body["top_affected_hosts"][0]["host_id"] == "10001"
    assert body["resource_trends"][1]["filesystem"] == "/var"


def test_zabbix_route_is_mounted_through_shared_router() -> None:
    app = create_app()
    paths = set(app.openapi()["paths"])

    assert "/api/dashboard/zabbix" in paths

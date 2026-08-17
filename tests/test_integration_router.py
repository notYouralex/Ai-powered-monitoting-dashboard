from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.main import create_app


def test_all_source_routers_exist_and_are_mountable() -> None:
    from app.integrations.freshservice.router import router as freshservice_router
    from app.integrations.snipe_it.router import router as snipe_it_router
    from app.integrations.wazuh.router import router as wazuh_router
    from app.integrations.zabbix.router import router as zabbix_router

    assert isinstance(wazuh_router, APIRouter)
    assert isinstance(zabbix_router, APIRouter)
    assert isinstance(snipe_it_router, APIRouter)
    assert isinstance(freshservice_router, APIRouter)


def test_shared_router_contains_freshservice_dashboard_route() -> None:
    app = create_app()
    paths = set(app.openapi()["paths"])
    assert "/api/dashboard/freshservice" in paths


def test_wazuh_router_is_mounted_through_shared_router() -> None:
    app = create_app()
    paths = set(app.openapi()["paths"])

    assert "/api/dashboard/wazuh" in paths


def test_application_starts_without_any_source_credentials() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Request-ID" in response.headers


def test_application_exposes_only_implemented_source_endpoints() -> None:
    app = create_app()
    paths = set(app.openapi()["paths"])

    assert "/api/dashboard/wazuh" in paths
    assert "/api/dashboard/zabbix" in paths
    assert "/api/dashboard/snipe-it" in paths
    assert "/api/dashboard/freshservice" in set(app.openapi()["paths"])
    assert "/api/integrations/health" not in paths

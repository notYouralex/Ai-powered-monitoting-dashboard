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


def test_shared_router_contains_no_functional_routes_yet() -> None:
    from app.integrations.router import router

    paths = {route.path for route in router.routes if hasattr(route, "path")}
    assert paths == set()


def test_application_starts_without_any_source_credentials() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Request-ID" in response.headers


def test_router_scaffold_adds_no_source_endpoints_yet() -> None:
    app = create_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/api/dashboard/wazuh" not in paths
    assert "/api/dashboard/zabbix" not in paths
    assert "/api/dashboard/snipe-it" not in paths
    assert "/api/dashboard/freshservice" not in paths
    assert "/api/integrations/health" not in paths

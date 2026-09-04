import asyncio
from types import SimpleNamespace

from app.core.config import Settings
from app.worker import run_zabbix_refresh_once


def make_settings(*, configured: bool) -> Settings:
    values = {
        "app_env": "test",
        "app_secret_key": "t" * 48,
        "database_url": "sqlite:///:memory:",
        "_env_file": None,
    }
    if configured:
        values.update(
            zabbix_base_url="https://zabbix.example/api_jsonrpc.php",
            zabbix_api_token="test-token",
        )
    return Settings(**values)


def test_worker_skips_zabbix_when_source_not_configured() -> None:
    called = False

    def client_factory(_settings):
        nonlocal called
        called = True
        raise AssertionError("client should not be created")

    result = asyncio.run(
        run_zabbix_refresh_once(
            settings=make_settings(configured=False),
            session_factory=lambda: None,
            client_factory=client_factory,
        )
    )

    assert result == "not_configured"
    assert called is False


def test_worker_delegates_configured_zabbix_refresh_to_cache_service(monkeypatch) -> None:
    client = object()
    seen = {}

    class SessionContext:
        def __enter__(self):
            seen["db"] = object()
            return seen["db"]

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeRefreshService:
        def __init__(self, received_client):
            seen["client"] = received_client

        async def refresh(self, db):
            seen["refresh_db"] = db
            return SimpleNamespace(status="success")

    def fake_correlate(db):
        seen["correlation_db"] = db
        return 1

    monkeypatch.setattr("app.worker.ZabbixCacheRefreshService", FakeRefreshService)
    monkeypatch.setattr("app.worker.correlate_zabbix_cache", fake_correlate)

    result = asyncio.run(
        run_zabbix_refresh_once(
            settings=make_settings(configured=True),
            session_factory=SessionContext,
            client_factory=lambda _settings: client,
        )
    )

    assert result == "success"
    assert seen["client"] is client
    assert seen["refresh_db"] is seen["db"]
    assert seen["correlation_db"] is seen["db"]

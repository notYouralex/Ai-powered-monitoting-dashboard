import asyncio
from types import SimpleNamespace

from app.core.config import Settings
from app.worker import run_snipe_it_sync_once


def make_settings(*, configured: bool) -> Settings:
    values = {
        "app_env": "test",
        "app_secret_key": "t" * 48,
        "database_url": "sqlite:///:memory:",
        "_env_file": None,
    }
    if configured:
        values.update(
            snipe_it_base_url="https://snipe.example",
            snipe_it_api_token="test-token",
        )
    return Settings(**values)


def test_worker_skips_source_when_snipe_it_not_configured() -> None:
    called = False

    def client_factory(_settings):
        nonlocal called
        called = True
        raise AssertionError("client should not be created")

    result = asyncio.run(
        run_snipe_it_sync_once(
            settings=make_settings(configured=False),
            session_factory=lambda: None,
            client_factory=client_factory,
        )
    )

    assert result == "not_configured"
    assert called is False


def test_worker_correlates_assets_after_successful_snipe_it_sync(monkeypatch) -> None:
    client = object()
    seen = {}

    class SessionContext:
        def __enter__(self):
            seen["db"] = object()
            return seen["db"]

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeSyncService:
        def __init__(self, received_client):
            seen["client"] = received_client

        async def sync(self, db):
            seen["sync_db"] = db
            return SimpleNamespace(status="success")

    def fake_correlate(db):
        seen["correlation_db"] = db
        return 1

    monkeypatch.setattr("app.worker.SnipeItSyncService", FakeSyncService)
    monkeypatch.setattr("app.worker.correlate_snipe_it_assets", fake_correlate)

    result = asyncio.run(
        run_snipe_it_sync_once(
            settings=make_settings(configured=True),
            session_factory=SessionContext,
            client_factory=lambda _settings: client,
        )
    )

    assert result == "success"
    assert seen["client"] is client
    assert seen["sync_db"] is seen["db"]
    assert seen["correlation_db"] is seen["db"]

import asyncio

from app.core.config import Settings
from app.worker import run_snipe_it_sync_once


def test_worker_skips_source_when_snipe_it_not_configured() -> None:
    settings = Settings(
        app_env="test",
        app_secret_key="t" * 48,
        database_url="sqlite:///:memory:",
        _env_file=None,
    )
    called = False

    def client_factory(_settings):
        nonlocal called
        called = True
        raise AssertionError("client should not be created")

    result = asyncio.run(
        run_snipe_it_sync_once(
            settings=settings,
            session_factory=lambda: None,
            client_factory=client_factory,
        )
    )

    assert result == "not_configured"
    assert called is False

import asyncio
from types import SimpleNamespace

from app.core.config import Settings
from app.worker import run_wazuh_correlation_once, run_worker


def make_settings(*, configured: bool) -> Settings:
    values = {
        "app_env": "test",
        "app_secret_key": "t" * 48,
        "database_url": "sqlite:///:memory:",
        "_env_file": None,
    }
    if configured:
        values.update(
            wazuh_base_url="https://wazuh.example:55000",
            wazuh_username="reader",
            wazuh_password="test-password",
        )
    return Settings(**values)


def test_worker_skips_wazuh_correlation_when_server_not_configured() -> None:
    called = False

    def client_factory(_settings):
        nonlocal called
        called = True
        raise AssertionError("client should not be created")

    result = asyncio.run(
        run_wazuh_correlation_once(
            settings=make_settings(configured=False),
            session_factory=lambda: None,
            client_factory=client_factory,
        )
    )

    assert result == "not_configured"
    assert called is False


def test_worker_fetches_wazuh_agents_and_correlates_them(monkeypatch) -> None:
    agent = SimpleNamespace(agent_id="007")
    seen = {}

    class FakeClient:
        async def list_agents(self):
            return [agent]

    class SessionContext:
        def __enter__(self):
            seen["db"] = object()
            return seen["db"]

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_correlate(db, agents, *, observed_at):
        seen["correlation_db"] = db
        seen["agents"] = agents
        seen["observed_at"] = observed_at
        return 1

    monkeypatch.setattr("app.worker.correlate_wazuh_agents", fake_correlate)

    result = asyncio.run(
        run_wazuh_correlation_once(
            settings=make_settings(configured=True),
            session_factory=SessionContext,
            client_factory=lambda _settings: FakeClient(),
        )
    )

    assert result == "success"
    assert seen["correlation_db"] is seen["db"]
    assert seen["agents"] == [agent]
    assert seen["observed_at"].tzinfo is not None


def test_worker_starts_wazuh_correlation_loop_with_existing_source_loops(monkeypatch) -> None:
    settings = make_settings(configured=False)
    called = []

    async def fake_loop(name):
        called.append(name)

    monkeypatch.setattr("app.worker.get_settings", lambda: settings)
    monkeypatch.setattr("app.worker._run_freshservice_loop", lambda _settings: fake_loop("freshservice"))
    monkeypatch.setattr("app.worker._run_snipe_it_loop", lambda _settings: fake_loop("snipe_it"))
    monkeypatch.setattr("app.worker._run_zabbix_loop", lambda _settings: fake_loop("zabbix"))
    monkeypatch.setattr(
        "app.worker._run_wazuh_correlation_loop",
        lambda _settings: fake_loop("wazuh"),
    )

    asyncio.run(run_worker())

    assert set(called) == {"freshservice", "snipe_it", "zabbix", "wazuh"}

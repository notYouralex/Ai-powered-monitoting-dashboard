from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dockerfile_runs_application_as_non_root_user() -> None:
    dockerfile = read("Dockerfile")

    assert "USER app" in dockerfile
    assert "CMD" in dockerfile and "uvicorn" in dockerfile


def test_compose_requires_secrets_and_binds_api_to_loopback() -> None:
    compose = read("compose.yaml")

    assert "APP_SECRET_KEY: ${APP_SECRET_KEY:?" in compose
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?" in compose
    assert '"127.0.0.1:${APP_PORT:-8000}:8000"' in compose
    assert "replace-with-a-long-random-secret" not in compose
    assert "replace-me" not in compose


def test_compose_passes_optional_integration_settings_to_api() -> None:
    compose = read("compose.yaml")

    expected_settings = (
        "WAZUH_BASE_URL",
        "WAZUH_USERNAME",
        "WAZUH_PASSWORD",
        "WAZUH_VERIFY_TLS",
        "WAZUH_CA_BUNDLE",
        "WAZUH_TIMEOUT_SECONDS",
        "ZABBIX_BASE_URL",
        "ZABBIX_API_TOKEN",
        "ZABBIX_VERIFY_TLS",
        "ZABBIX_CA_BUNDLE",
        "ZABBIX_TIMEOUT_SECONDS",
        "SNIPE_IT_BASE_URL",
        "SNIPE_IT_API_TOKEN",
        "SNIPE_IT_VERIFY_TLS",
        "SNIPE_IT_CA_BUNDLE",
        "SNIPE_IT_TIMEOUT_SECONDS",
        "FRESHSERVICE_BASE_URL",
        "FRESHSERVICE_API_KEY",
        "FRESHSERVICE_VERIFY_TLS",
        "FRESHSERVICE_CA_BUNDLE",
        "FRESHSERVICE_TIMEOUT_SECONDS",
        "FRESHSERVICE_SYNC_INTERVAL_SECONDS",
    )

    for setting in expected_settings:
        assert f"{setting}: ${{{setting}" in compose


def test_postgresql_has_healthcheck_and_persistent_volume() -> None:
    compose = read("compose.yaml")

    assert "postgresql:" in compose
    assert "healthcheck:" in compose
    assert "pg_isready" in compose
    assert "postgres-data:" in compose


def test_api_has_healthcheck_for_worker_startup_ordering() -> None:
    compose = read("compose.yaml")
    api = compose.split("fastapi-api:", 1)[1].split("background-worker:", 1)[0]

    assert "healthcheck:" in api
    assert "/health" in api


def test_entrypoint_applies_migrations_before_starting_application() -> None:
    entrypoint = read("docker/entrypoint.sh")

    migration_index = entrypoint.index("alembic upgrade head")
    exec_index = entrypoint.index('exec "$@"')
    assert migration_index < exec_index


def test_compose_defines_isolated_background_worker_without_host_port() -> None:
    compose = read("compose.yaml")

    assert "background-worker:" in compose
    worker = compose.split("background-worker:", 1)[1]
    assert 'command: ["python", "-m", "app.worker"]' in worker
    assert 'RUN_MIGRATIONS: "false"' in worker
    assert "fastapi-api:" in worker and "condition: service_healthy" in worker
    assert "FRESHSERVICE_API_KEY" in worker
    assert "FRESHSERVICE_SYNC_INTERVAL_SECONDS" in worker
    assert "ports:" not in worker

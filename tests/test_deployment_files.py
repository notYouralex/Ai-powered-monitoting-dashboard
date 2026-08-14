from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dockerfile_runs_application_as_non_root_user() -> None:
    dockerfile = read("Dockerfile")

    assert "USER app" in dockerfile
    assert "CMD" in dockerfile and "uvicorn" in dockerfile


def test_dockerfile_installs_runtime_dependencies_from_uv_lock() -> None:
    dockerfile = read("Dockerfile")

    assert "COPY pyproject.toml uv.lock README.md ./" in dockerfile
    assert "python -m pip install --no-cache-dir uv==0.12.2" in dockerfile
    assert "uv sync --frozen --no-editable --no-install-project" in dockerfile
    assert 'PATH="/app/.venv/bin:$PATH"' in dockerfile
    assert "python -m pip install --no-cache-dir ." not in dockerfile


def test_compose_requires_secrets_and_binds_api_to_loopback() -> None:
    compose = read("compose.yaml")
    api = compose.split("fastapi-api:", 1)[1].split("background-worker:", 1)[0]

    assert "APP_SECRET_KEY: ${APP_SECRET_KEY:?" in compose
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?" in compose
    assert "network_mode: host" in api
    assert 'command: ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "${APP_PORT:-8000}"]' in api
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
        "WAZUH_INDEXER_BASE_URL",
        "WAZUH_INDEXER_USERNAME",
        "WAZUH_INDEXER_PASSWORD",
        "WAZUH_INDEXER_VERIFY_TLS",
        "WAZUH_INDEXER_CA_BUNDLE",
        "WAZUH_INDEXER_TIMEOUT_SECONDS",
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
    postgresql = compose.split("postgresql:", 1)[1].split("fastapi-api:", 1)[0]

    assert "healthcheck:" in postgresql
    assert "pg_isready" in postgresql
    assert "postgres-data:" in compose
    assert '"127.0.0.1:${POSTGRES_HOST_PORT:-55432}:5432"' in postgresql


def test_api_uses_loopback_postgres_and_read_only_wazuh_certificates() -> None:
    compose = read("compose.yaml")
    api = compose.split("fastapi-api:", 1)[1].split("background-worker:", 1)[0]

    assert "@127.0.0.1:${POSTGRES_HOST_PORT:-55432}/" in api
    assert "./.runtime-certs:/run/wazuh-certs:ro" in api


def test_background_worker_remains_on_compose_network() -> None:
    compose = read("compose.yaml")
    worker = compose.split("background-worker:", 1)[1]

    assert "network_mode: host" not in worker
    assert "@postgresql:5432/" in worker


def test_api_has_healthcheck_for_worker_startup_ordering() -> None:
    compose = read("compose.yaml")
    api = compose.split("fastapi-api:", 1)[1].split("background-worker:", 1)[0]

    assert "healthcheck:" in api
    assert "/health" in api


def test_background_worker_receives_zabbix_settings() -> None:
    compose = read("compose.yaml")
    worker = compose.split("background-worker:", 1)[1]

    expected_settings = (
        "ZABBIX_BASE_URL",
        "ZABBIX_API_TOKEN",
        "ZABBIX_VERIFY_TLS",
        "ZABBIX_CA_BUNDLE",
        "ZABBIX_TIMEOUT_SECONDS",
    )

    for setting in expected_settings:
        assert f"{setting}: ${{{setting}" in worker


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

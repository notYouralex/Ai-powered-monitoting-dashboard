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


def test_postgresql_has_healthcheck_and_persistent_volume() -> None:
    compose = read("compose.yaml")

    assert "postgresql:" in compose
    assert "healthcheck:" in compose
    assert "pg_isready" in compose
    assert "postgres-data:" in compose


def test_entrypoint_applies_migrations_before_starting_application() -> None:
    entrypoint = read("docker/entrypoint.sh")

    migration_index = entrypoint.index("alembic upgrade head")
    exec_index = entrypoint.index('exec "$@"')
    assert migration_index < exec_index

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_postgresql_backup_restore_runbook_is_secret_safe_and_reversible() -> None:
    runbook = read("docs/deployment/postgresql-backup-restore.md")

    assert "umask 077" in runbook
    assert "pg_dump" in runbook
    assert "--format=custom" in runbook
    assert "--no-owner" in runbook
    assert "--no-privileges" in runbook
    assert "sha256sum" in runbook
    assert "pg_restore --list" in runbook
    assert "docker compose stop background-worker fastapi-api" in runbook
    assert "alembic heads" in runbook
    assert "alembic current" in runbook
    assert "explicit approval" in runbook.lower()
    assert "destructive" in runbook.lower()
    assert "do not commit" in runbook.lower()
    assert "company network" in runbook.lower()
    assert "POSTGRES_PASSWORD=" not in runbook


def test_backend_acceptance_runbook_covers_runtime_sources_and_security() -> None:
    runbook = read("docs/deployment/backend-acceptance.md")

    assert "docker compose config --quiet" in runbook
    assert "docker compose ps" in runbook
    assert "alembic heads" in runbook
    assert "alembic current" in runbook
    assert "GET /health" in runbook
    assert "/api/dashboard/executive" in runbook
    assert "/api/dashboard/wazuh" in runbook
    assert "/api/dashboard/zabbix" in runbook
    assert "/api/dashboard/snipe-it" in runbook
    assert "/api/dashboard/freshservice" in runbook
    assert "/api/integrations/health" in runbook
    assert "/api/ai/status" in runbook
    assert "healthy" in runbook
    assert "degraded" in runbook
    assert "unavailable" in runbook
    assert "not_configured" in runbook
    assert "read-only" in runbook.lower()
    assert "ss -ltn" in runbook
    assert "GRAFANA_API_TOKEN" in runbook
    assert "do not" in runbook.lower()

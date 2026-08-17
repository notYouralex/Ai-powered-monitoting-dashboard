from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_usernames_are_unique_and_account_flags_have_safe_defaults() -> None:
    from app.db.base import Base
    from app.db.models import User
    from app.db.session import create_engine_for_url

    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(User(username="alice", password_hash="hash-1"))
        db.commit()

        user = db.query(User).filter_by(username="alice").one()
        assert user.is_active is True
        assert user.is_admin is False

        db.add(User(username="alice", password_hash="hash-2"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_auth_session_stores_only_token_digest_and_expiry_metadata() -> None:
    from app.db.base import Base
    from app.db.models import AuthSession, User
    from app.db.session import create_engine_for_url

    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        user = User(username="admin", password_hash="hash", is_admin=True)
        db.add(user)
        db.flush()

        auth_session = AuthSession(
            user_id=user.id,
            token_digest="a" * 64,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=12),
        )
        db.add(auth_session)
        db.commit()

        assert auth_session.token_digest == "a" * 64
        assert not hasattr(auth_session, "token")
        assert auth_session.revoked_at is None

    columns = {column["name"]: column for column in inspect(engine).get_columns("auth_sessions")}
    assert "token_digest" in columns
    assert "token" not in columns
    assert "last_seen_at" in columns
    assert "idle_expires_at" in columns
    assert "absolute_expires_at" in columns


def test_auth_audit_and_login_attempt_records_persist() -> None:
    from app.db.base import Base
    from app.db.models import AuthAuditEvent, LoginAttempt
    from app.db.session import create_engine_for_url

    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            AuthAuditEvent(
                event_type="login",
                username="alice",
                success=False,
                reason="invalid_credentials",
            )
        )
        db.add(LoginAttempt(username="alice", success=False))
        db.commit()

        audit = db.query(AuthAuditEvent).one()
        attempt = db.query(LoginAttempt).one()

        assert audit.event_type == "login"
        assert audit.success is False
        assert audit.reason == "invalid_credentials"
        assert attempt.username == "alice"
        assert attempt.success is False


def test_initial_migration_creates_login_attempt_primary_key(tmp_path) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    database_path = tmp_path / "migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    primary_key = inspect(engine).get_pk_constraint("login_attempts")
    assert primary_key["constrained_columns"] == ["id"]


def test_freshservice_persistence_schema_has_stable_ticket_and_sync_keys() -> None:
    from app.db.base import Base
    from app.db.session import create_engine_for_url

    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    ticket_columns = {column["name"] for column in inspector.get_columns("tickets")}
    assert {
        "source_ticket_id",
        "subject",
        "status",
        "priority",
        "source_created_at",
        "source_updated_at",
        "synced_at",
    }.issubset(ticket_columns)

    unique_constraints = inspector.get_unique_constraints("tickets")
    assert any(
        constraint["column_names"] == ["source_ticket_id"]
        for constraint in unique_constraints
    )

    sync_columns = {column["name"] for column in inspector.get_columns("sync_runs")}
    assert {
        "source",
        "sync_type",
        "status",
        "started_at",
        "completed_at",
        "records_received",
        "records_upserted",
        "error_code",
    }.issubset(sync_columns)


def test_alembic_head_creates_freshservice_sync_tables(tmp_path) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    database_path = tmp_path / "freshservice-migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    tables = set(inspect(engine).get_table_names())
    assert "tickets" in tables
    assert "sync_runs" in tables


def test_zabbix_dashboard_cache_round_trips_normalized_json() -> None:
    from app.db.base import Base
    from app.db.models import ZabbixDashboardCache
    from app.db.session import create_engine_for_url

    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    refreshed_at = datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc)
    snapshot = {
        "source": "zabbix",
        "observed_at": "2026-08-14T01:00:00Z",
        "is_stale": False,
    }

    with Session(engine) as db:
        db.add(
            ZabbixDashboardCache(
                id=1,
                snapshot=snapshot,
                refreshed_at=refreshed_at,
            )
        )
        db.commit()
        db.expire_all()

        cached = db.get(ZabbixDashboardCache, 1)
        assert cached is not None
        assert cached.snapshot == snapshot
        assert cached.refreshed_at == refreshed_at


def test_alembic_head_creates_zabbix_dashboard_cache_table(tmp_path) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    database_path = tmp_path / "zabbix-cache-migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    columns = {
        column["name"] for column in inspect(engine).get_columns("zabbix_dashboard_cache")
    }
    assert columns == {"id", "snapshot", "refreshed_at"}


def test_snipe_it_asset_schema_has_stable_source_and_reporting_fields() -> None:
    from app.db.base import Base
    from app.db.session import create_engine_for_url

    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    columns = {column["name"] for column in inspector.get_columns("assets")}
    assert {
        "source_asset_id",
        "asset_tag",
        "name",
        "serial",
        "model",
        "category",
        "manufacturer",
        "status_label",
        "status_type",
        "assigned_to_id",
        "assigned_type",
        "location",
        "purchase_date",
        "warranty_months",
        "warranty_expires",
        "synced_at",
    }.issubset(columns)

    unique_constraints = inspector.get_unique_constraints("assets")
    assert any(
        constraint["column_names"] == ["source_asset_id"]
        for constraint in unique_constraints
    )


def test_alembic_head_creates_snipe_it_assets_table(tmp_path) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    database_path = tmp_path / "snipe-it-assets-migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    columns = {column["name"] for column in inspect(engine).get_columns("assets")}
    assert "source_asset_id" in columns
    assert "asset_tag" in columns
    assert "serial" in columns
    assert "synced_at" in columns

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_head_creates_device_correlation_tables(tmp_path) -> None:
    database_path = tmp_path / "device-correlation-migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    inspector = inspect(engine)
    assert "devices" in inspector.get_table_names()
    assert "device_source_links" in inspector.get_table_names()

    device_columns = {column["name"] for column in inspector.get_columns("devices")}
    assert {
        "canonical_name",
        "hostname",
        "ip",
        "serial",
        "asset_tag",
        "os",
        "device_type",
        "location",
        "correlation_confidence",
        "created_at",
        "updated_at",
    }.issubset(device_columns)

    link_columns = {column["name"] for column in inspector.get_columns("device_source_links")}
    assert {
        "device_id",
        "source",
        "source_record_id",
        "identifiers",
        "match_method",
        "confidence",
        "manual_override",
        "last_seen_at",
        "created_at",
    }.issubset(link_columns)

    unique_constraints = inspector.get_unique_constraints("device_source_links")
    assert any(
        constraint["column_names"] == ["source", "source_record_id"]
        for constraint in unique_constraints
    )

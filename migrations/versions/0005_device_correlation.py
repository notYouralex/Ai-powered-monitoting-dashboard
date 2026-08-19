"""Create canonical device correlation tables.

Revision ID: 0005_device_correlation
Revises: 0004_snipe_it_assets
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_device_correlation"
down_revision: str | None = "0004_snipe_it_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("serial", sa.String(length=255), nullable=True),
        sa.Column("asset_tag", sa.String(length=255), nullable=True),
        sa.Column("os", sa.String(length=255), nullable=True),
        sa.Column("device_type", sa.String(length=255), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("correlation_confidence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_devices_hostname", "devices", ["hostname"], unique=False)
    op.create_index("ix_devices_ip", "devices", ["ip"], unique=False)
    op.create_index("ix_devices_serial", "devices", ["serial"], unique=False)
    op.create_index("ix_devices_asset_tag", "devices", ["asset_tag"], unique=False)

    op.create_table(
        "device_source_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "device_id",
            sa.Integer(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=False),
        sa.Column("identifiers", sa.JSON(), nullable=False),
        sa.Column("match_method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source",
            "source_record_id",
            name="uq_device_source_links_source_record",
        ),
    )
    op.create_index(
        "ix_device_source_links_device_source",
        "device_source_links",
        ["device_id", "source"],
        unique=False,
    )
    op.create_index(
        "ix_device_source_links_last_seen_at",
        "device_source_links",
        ["last_seen_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_device_source_links_last_seen_at",
        table_name="device_source_links",
    )
    op.drop_index(
        "ix_device_source_links_device_source",
        table_name="device_source_links",
    )
    op.drop_table("device_source_links")
    op.drop_index("ix_devices_asset_tag", table_name="devices")
    op.drop_index("ix_devices_serial", table_name="devices")
    op.drop_index("ix_devices_ip", table_name="devices")
    op.drop_index("ix_devices_hostname", table_name="devices")
    op.drop_table("devices")

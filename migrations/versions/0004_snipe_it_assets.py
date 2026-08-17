"""Create normalized Snipe-IT asset synchronization table.

Revision ID: 0004_snipe_it_assets
Revises: 0003_zabbix_dashboard_cache
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_snipe_it_assets"
down_revision: str | None = "0003_zabbix_dashboard_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_asset_id", sa.BigInteger(), nullable=False),
        sa.Column("asset_tag", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("serial", sa.String(length=255), nullable=True),
        sa.Column("model_id", sa.BigInteger(), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("manufacturer_id", sa.BigInteger(), nullable=True),
        sa.Column("manufacturer", sa.String(length=255), nullable=True),
        sa.Column("status_label_id", sa.BigInteger(), nullable=True),
        sa.Column("status_label", sa.String(length=255), nullable=True),
        sa.Column("status_type", sa.String(length=64), nullable=True),
        sa.Column("assigned_to_id", sa.BigInteger(), nullable=True),
        sa.Column("assigned_type", sa.String(length=64), nullable=True),
        sa.Column("location_id", sa.BigInteger(), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("warranty_months", sa.Integer(), nullable=True),
        sa.Column("warranty_expires", sa.Date(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_asset_id"),
    )
    op.create_index("ix_assets_asset_tag", "assets", ["asset_tag"], unique=False)
    op.create_index("ix_assets_serial", "assets", ["serial"], unique=False)
    op.create_index("ix_assets_status_label", "assets", ["status_label"], unique=False)
    op.create_index("ix_assets_category", "assets", ["category"], unique=False)
    op.create_index("ix_assets_synced_at", "assets", ["synced_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_assets_synced_at", table_name="assets")
    op.drop_index("ix_assets_category", table_name="assets")
    op.drop_index("ix_assets_status_label", table_name="assets")
    op.drop_index("ix_assets_serial", table_name="assets")
    op.drop_index("ix_assets_asset_tag", table_name="assets")
    op.drop_table("assets")

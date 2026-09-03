"""Add Snipe-IT company fields for asset reporting.

Revision ID: 0006_snipe_it_company
Revises: 0005_device_correlation
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_snipe_it_company"
down_revision: str | None = "0005_device_correlation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("company_id", sa.BigInteger(), nullable=True))
    op.add_column("assets", sa.Column("company", sa.String(length=255), nullable=True))
    op.create_index("ix_assets_company", "assets", ["company"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_assets_company", table_name="assets")
    op.drop_column("assets", "company")
    op.drop_column("assets", "company_id")

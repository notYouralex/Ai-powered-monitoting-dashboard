"""Create normalized Zabbix dashboard cache.

Revision ID: 0003_zabbix_dashboard_cache
Revises: 0002_freshservice_sync
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_zabbix_dashboard_cache"
down_revision: str | None = "0002_freshservice_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "zabbix_dashboard_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("zabbix_dashboard_cache")

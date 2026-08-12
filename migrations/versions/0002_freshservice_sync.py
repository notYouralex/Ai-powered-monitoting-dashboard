"""Create Freshservice ticket synchronization tables.

Revision ID: 0002_freshservice_sync
Revises: 0001_auth_foundation
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_freshservice_sync"
down_revision: str | None = "0001_auth_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.String(length=1024), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority_code", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("ticket_type", sa.String(length=256), nullable=True),
        sa.Column("category", sa.String(length=256), nullable=True),
        sa.Column("sub_category", sa.String(length=256), nullable=True),
        sa.Column("item_category", sa.String(length=256), nullable=True),
        sa.Column("requester_id", sa.BigInteger(), nullable=True),
        sa.Column("requested_for_id", sa.BigInteger(), nullable=True),
        sa.Column("responder_id", sa.BigInteger(), nullable=True),
        sa.Column("group_id", sa.BigInteger(), nullable=True),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("workspace_id", sa.BigInteger(), nullable=True),
        sa.Column("source_code", sa.Integer(), nullable=True),
        sa.Column("due_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_response_due_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_escalated", sa.Boolean(), nullable=False),
        sa.Column("first_response_escalated", sa.Boolean(), nullable=False),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_ticket_id"),
    )
    op.create_index("ix_tickets_status", "tickets", ["status"], unique=False)
    op.create_index("ix_tickets_priority", "tickets", ["priority"], unique=False)
    op.create_index("ix_tickets_source_updated_at", "tickets", ["source_updated_at"], unique=False)
    op.create_index("ix_tickets_due_by", "tickets", ["due_by"], unique=False)

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("sync_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_received", sa.Integer(), nullable=False),
        sa.Column("records_upserted", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_sync_runs_source_started", "sync_runs", ["source", "started_at"], unique=False)
    op.create_index(
        "ix_sync_runs_source_status_completed",
        "sync_runs",
        ["source", "status", "completed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sync_runs_source_status_completed", table_name="sync_runs")
    op.drop_index("ix_sync_runs_source_started", table_name="sync_runs")
    op.drop_table("sync_runs")

    op.drop_index("ix_tickets_due_by", table_name="tickets")
    op.drop_index("ix_tickets_source_updated_at", table_name="tickets")
    op.drop_index("ix_tickets_priority", table_name="tickets")
    op.drop_index("ix_tickets_status", table_name="tickets")
    op.drop_table("tickets")

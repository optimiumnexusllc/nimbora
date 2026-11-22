"""Billing of human call minutes (enterprise PBX call logs)

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-11-21 23:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscription_plans",
        sa.Column("included_human_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "subscription_plans",
        sa.Column("human_overage_price_cents_per_minute", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pbx_connections",
        sa.Column("usage_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "human_call_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(16), nullable=False, server_default="pbx"),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("billable_seconds", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "source", "external_id", name="uq_human_call_usage_ext"
        ),
    )
    op.create_index("ix_human_call_usage_id", "human_call_usage", ["id"])
    op.create_index(
        "ix_human_call_usage_org_started",
        "human_call_usage",
        ["organization_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_human_call_usage_org_started", table_name="human_call_usage")
    op.drop_index("ix_human_call_usage_id", table_name="human_call_usage")
    op.drop_table("human_call_usage")
    op.drop_column("pbx_connections", "usage_synced_at")
    op.drop_column("subscription_plans", "human_overage_price_cents_per_minute")
    op.drop_column("subscription_plans", "included_human_minutes")

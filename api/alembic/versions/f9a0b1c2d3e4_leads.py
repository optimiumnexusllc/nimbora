"""Leads: qualification (need, budget, timeline) and pipeline

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-11-22 19:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from alembic_postgresql_enum import TableReference

revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TOOL_CATEGORIES = [
    "http_api",
    "end_call",
    "transfer_call",
    "transfer_agent",
    "calculator",
    "native",
    "integration",
    "mcp",
    "schedule_callback",
    "book_appointment",
    "send_message",
    "create_ticket",
    "search_catalog",
]


def _sync_tool_categories(values: list[str]) -> None:
    op.sync_enum_values(
        enum_schema="public",
        enum_name="tool_category",
        new_values=values,
        affected_columns=[
            TableReference(
                table_schema="public", table_name="tools", column_name="category"
            )
        ],
        enum_values_to_rename=[],
    )


def upgrade() -> None:
    _sync_tool_categories(TOOL_CATEGORIES + ["qualify_lead"])
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customer_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("company", sa.String(128), nullable=True),
        sa.Column("need", sa.Text(), nullable=True),
        sa.Column("budget_min", sa.BigInteger(), nullable=True),
        sa.Column("budget_max", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="XOF"),
        sa.Column("timeline", sa.String(128), nullable=True),
        sa.Column("decision_maker", sa.Boolean(), nullable=True),
        sa.Column("interests", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("stage", sa.String(16), nullable=False, server_default="new"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("owner", sa.String(128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("lost_reason", sa.String(255), nullable=True),
        sa.Column("next_action", sa.String(255), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workflow_run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_leads_id", "leads", ["id"])
    op.create_index("ix_leads_org_stage", "leads", ["organization_id", "stage"])
    op.create_index("ix_leads_org_phone", "leads", ["organization_id", "phone"])


def downgrade() -> None:
    op.drop_index("ix_leads_org_phone", table_name="leads")
    op.drop_index("ix_leads_org_stage", table_name="leads")
    op.drop_index("ix_leads_id", table_name="leads")
    op.drop_table("leads")
    op.execute("DELETE FROM tools WHERE category = 'qualify_lead'")
    _sync_tool_categories(TOOL_CATEGORIES)

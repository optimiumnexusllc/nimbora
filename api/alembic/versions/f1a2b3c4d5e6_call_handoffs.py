"""Call handoffs: AI -> human transfer context shown in agent softphones.

Revision ID: f1a2b3c4d5e6
Revises: e7a1c0de5a01
"""

import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e7a1c0de5a01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "call_handoffs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("queue_slug", sa.String(length=48), nullable=True),
        sa.Column("caller_number", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("customer_name", sa.String(length=128), nullable=True),
        sa.Column("sentiment", sa.String(length=16), nullable=True),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("collected_data", sa.JSON(), nullable=False),
        sa.Column("transcript", sa.JSON(), nullable=False),
        sa.Column("summary_status", sa.String(length=16), nullable=False),
        sa.Column(
            "answered_by_agent_id",
            sa.Integer(),
            sa.ForeignKey("contact_center_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_call_handoffs_org_created",
        "call_handoffs",
        ["organization_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_call_handoffs_org_created", table_name="call_handoffs")
    op.drop_table("call_handoffs")

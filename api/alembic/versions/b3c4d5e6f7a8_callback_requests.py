"""Callback requests (AI tool, abandoned queue calls, manual).

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None

STATUSES = ("pending", "in_progress", "done", "failed", "canceled")


def upgrade():
    status = postgresql.ENUM(*STATUSES, name="callback_status", create_type=False)
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "callback_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("customer_name", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("assign_to", sa.String(length=8), nullable=False),
        sa.Column("queue_slug", sa.String(length=48), nullable=True),
        sa.Column(
            "workflow_id",
            sa.Integer(),
            sa.ForeignKey("workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", status, nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "origin_workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "callback_workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "handoff_id",
            sa.String(length=36),
            sa.ForeignKey("call_handoffs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_agent_id",
            sa.Integer(),
            sa.ForeignKey("contact_center_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_callback_requests_id", "callback_requests", ["id"])
    op.create_index(
        "ix_callback_requests_due", "callback_requests", ["status", "scheduled_at"]
    )
    op.create_index(
        "ix_callback_requests_org_status",
        "callback_requests",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_callback_requests_org_phone",
        "callback_requests",
        ["organization_id", "phone"],
    )


def downgrade():
    op.drop_table("callback_requests")
    postgresql.ENUM(name="callback_status").drop(op.get_bind(), checkfirst=True)

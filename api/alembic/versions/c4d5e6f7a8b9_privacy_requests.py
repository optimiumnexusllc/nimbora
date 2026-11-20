"""GDPR request register.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "privacy_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("subject_hint", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "requested_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_privacy_requests_id", "privacy_requests", ["id"])
    op.create_index(
        "ix_privacy_requests_org_created",
        "privacy_requests",
        ["organization_id", "created_at"],
    )
    # Retention sweeps scan old runs per workflow by date.
    op.create_index("idx_workflow_runs_created_at", "workflow_runs", ["created_at"])


def downgrade():
    op.drop_index("idx_workflow_runs_created_at", table_name="workflow_runs")
    op.drop_table("privacy_requests")

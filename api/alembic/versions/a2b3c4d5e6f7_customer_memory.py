"""Customer memory: profiles per organization and their call history.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("phone_suffix", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("last_summary", sa.Text(), nullable=True),
        sa.Column("last_sentiment", sa.String(length=16), nullable=True),
        sa.Column("total_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "phone", name="_customer_org_phone_uc"),
    )
    op.create_index("ix_customer_profiles_id", "customer_profiles", ["id"])
    op.create_index(
        "ix_customer_profiles_org_suffix",
        "customer_profiles",
        ["organization_id", "phone_suffix"],
    )
    op.create_index(
        "ix_customer_profiles_org_last_seen",
        "customer_profiles",
        ["organization_id", "last_seen_at"],
    )
    op.create_table(
        "customer_interactions",
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
            sa.ForeignKey("customer_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("direction", sa.String(length=16), nullable=True),
        sa.Column("agent_name", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.String(length=16), nullable=True),
        sa.Column("outcome", sa.String(length=64), nullable=True),
        sa.Column("transferred_to_queue", sa.String(length=48), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workflow_run_id", name="_customer_interaction_run_uc"),
    )
    op.create_index("ix_customer_interactions_id", "customer_interactions", ["id"])
    op.create_index(
        "ix_customer_interactions_customer",
        "customer_interactions",
        ["customer_id", "created_at"],
    )


def downgrade():
    op.drop_table("customer_interactions")
    op.drop_table("customer_profiles")

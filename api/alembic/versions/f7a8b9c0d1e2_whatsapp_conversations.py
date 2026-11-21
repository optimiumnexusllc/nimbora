"""WhatsApp conversations (messaging) and interaction channel.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
"""

import sqlalchemy as sa
from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "customer_interactions", sa.Column("channel", sa.String(length=16), nullable=True)
    )
    op.create_table(
        "whatsapp_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "telephony_configuration_id",
            sa.Integer(),
            sa.ForeignKey("telephony_configurations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone_number_id", sa.String(length=64), nullable=False),
        sa.Column("business_number", sa.String(length=32), nullable=True),
        sa.Column("customer_wa_id", sa.String(length=32), nullable=False),
        sa.Column("customer_name", sa.String(length=128), nullable=True),
        sa.Column(
            "workflow_id",
            sa.Integer(),
            sa.ForeignKey("workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_whatsapp_conversations_id", "whatsapp_conversations", ["id"])
    op.create_index(
        "uq_whatsapp_conversations_open",
        "whatsapp_conversations",
        ["phone_number_id", "customer_wa_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_whatsapp_conversations_org",
        "whatsapp_conversations",
        ["organization_id", "last_inbound_at"],
    )


def downgrade():
    op.drop_table("whatsapp_conversations")
    op.drop_column("customer_interactions", "channel")

"""Enterprise PBX connection (white-labelled Wazo Platform engine)

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-11-21 07:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pbx_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(128), nullable=False, server_default="PBX"),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("password", sa.String(512), nullable=False),
        sa.Column("tenant_uuid", sa.String(64), nullable=True),
        sa.Column("verify_tls", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "ari_configuration_id",
            sa.Integer(),
            sa.ForeignKey("telephony_configurations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("incall_context", sa.String(128), nullable=True),
        sa.Column("webhook_token", sa.String(64), nullable=False, unique=True),
        sa.Column("webhook_subscription_uuid", sa.String(64), nullable=True),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("branding_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("pbx_connections")

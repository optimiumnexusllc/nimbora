"""Human call recordings from the enterprise PBX, kept by NIMBORA

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-11-21 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pbx_connections",
        sa.Column(
            "recording_policy",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "pbx_connections",
        sa.Column("recordings_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "pbx_call_recordings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cdr_id", sa.Integer(), nullable=False),
        sa.Column("recording_uuid", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(16), nullable=True),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("source_name", sa.String(128), nullable=True),
        sa.Column("destination", sa.String(64), nullable=True),
        sa.Column("destination_name", sa.String(128), nullable=True),
        sa.Column("customer_phone", sa.String(32), nullable=True),
        sa.Column("storage_backend", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column(
            "transcript_status", sa.String(16), nullable=False, server_default="none"
        ),
        sa.Column(
            "removed_from_pbx", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "recording_uuid", name="uq_pbx_recordings_org_uuid"
        ),
    )
    op.create_index(
        "ix_pbx_recordings_org_started",
        "pbx_call_recordings",
        ["organization_id", "started_at"],
    )
    op.create_index(
        "ix_pbx_call_recordings_customer_phone",
        "pbx_call_recordings",
        ["customer_phone"],
    )


def downgrade() -> None:
    op.drop_index("ix_pbx_call_recordings_customer_phone", "pbx_call_recordings")
    op.drop_index("ix_pbx_recordings_org_started", "pbx_call_recordings")
    op.drop_table("pbx_call_recordings")
    op.drop_column("pbx_connections", "recordings_synced_at")
    op.drop_column("pbx_connections", "recording_policy")

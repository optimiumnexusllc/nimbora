"""PBX supervision: settings and the log of listening sessions

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-11-21 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pbx_connections",
        sa.Column(
            "supervision_settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_table(
        "pbx_supervision_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("supervisor_user_uuid", sa.String(64), nullable=False),
        sa.Column("supervisor_name", sa.String(128), nullable=True),
        sa.Column("target_user_uuid", sa.String(64), nullable=False),
        sa.Column("target_name", sa.String(128), nullable=True),
        sa.Column("target_extension", sa.String(32), nullable=True),
        sa.Column("call_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_pbx_supervision_sessions_org_created",
        "pbx_supervision_sessions",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pbx_supervision_sessions_org_created", "pbx_supervision_sessions")
    op.drop_table("pbx_supervision_sessions")
    op.drop_column("pbx_connections", "supervision_settings")

"""Blocked numbers: callers refused and numbers never called by AI agents

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-11-21 13:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "blocked_numbers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False, server_default="both"),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "number", name="uq_blocked_numbers_org_number"
        ),
    )
    op.create_index(
        "ix_blocked_numbers_organization_id", "blocked_numbers", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_blocked_numbers_organization_id", table_name="blocked_numbers")
    op.drop_table("blocked_numbers")

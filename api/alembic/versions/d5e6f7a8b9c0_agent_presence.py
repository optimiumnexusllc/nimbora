"""Contact-center agent presence and supervisor flag.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""

import sqlalchemy as sa
from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "contact_center_agents",
        sa.Column(
            "presence", sa.String(length=16), nullable=False, server_default="available"
        ),
    )
    op.add_column(
        "contact_center_agents",
        sa.Column("presence_reason", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "contact_center_agents",
        sa.Column("presence_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "contact_center_agents",
        sa.Column(
            "is_supervisor", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade():
    op.drop_column("contact_center_agents", "is_supervisor")
    op.drop_column("contact_center_agents", "presence_changed_at")
    op.drop_column("contact_center_agents", "presence_reason")
    op.drop_column("contact_center_agents", "presence")

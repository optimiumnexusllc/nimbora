"""PBX: tenants created on the operator's shared PBX

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-11-21 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pbx_connections",
        sa.Column("managed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "pbx_connections",
        sa.Column(
            "provisioning",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("pbx_connections", "provisioning")
    op.drop_column("pbx_connections", "managed")

"""Resellers, their offers and client companies, invitation links

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-11-24 13:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resellers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column(
            "commission_bps", sa.Integer(), nullable=False, server_default="2000"
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("stripe_account_id", sa.String(length=64), nullable=True),
        sa.Column(
            "stripe_charges_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("stripe_account_id"),
    )
    op.create_index("ix_resellers_id", "resellers", ["id"])

    op.create_table(
        "reseller_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reseller_id",
            sa.Integer(),
            sa.ForeignKey("resellers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("reseller_id", "user_id", name="uq_reseller_member"),
    )
    op.create_index("ix_reseller_members_id", "reseller_members", ["id"])
    op.create_index("ix_reseller_members_user_id", "reseller_members", ["user_id"])

    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "reseller_id",
            sa.Integer(),
            sa.ForeignKey("resellers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_invitations_id", "invitations", ["id"])
    op.create_index(
        "ix_invitations_token_hash", "invitations", ["token_hash"], unique=True
    )

    op.add_column(
        "organizations",
        sa.Column(
            "reseller_id",
            sa.Integer(),
            sa.ForeignKey("resellers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_organizations_reseller_id", "organizations", ["reseller_id"])

    op.add_column(
        "subscription_plans",
        sa.Column(
            "reseller_id",
            sa.Integer(),
            sa.ForeignKey("resellers.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "subscription_plans",
        sa.Column(
            "base_plan_id",
            sa.Integer(),
            sa.ForeignKey("subscription_plans.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_subscription_plans_reseller_id", "subscription_plans", ["reseller_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_plans_reseller_id", table_name="subscription_plans")
    op.drop_column("subscription_plans", "base_plan_id")
    op.drop_column("subscription_plans", "reseller_id")
    op.drop_index("ix_organizations_reseller_id", table_name="organizations")
    op.drop_column("organizations", "reseller_id")
    op.drop_index("ix_invitations_token_hash", table_name="invitations")
    op.drop_index("ix_invitations_id", table_name="invitations")
    op.drop_table("invitations")
    op.drop_index("ix_reseller_members_user_id", table_name="reseller_members")
    op.drop_index("ix_reseller_members_id", table_name="reseller_members")
    op.drop_table("reseller_members")
    op.drop_index("ix_resellers_id", table_name="resellers")
    op.drop_table("resellers")

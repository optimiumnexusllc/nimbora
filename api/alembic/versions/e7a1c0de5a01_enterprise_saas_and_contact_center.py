"""Enterprise SaaS subscriptions and human contact center tables.

Adds subscription plans, one subscription per organization, and the
contact-center queues/agents that the platform Asterisk is generated from.

Revision ID: e7a1c0de5a01
Revises: f3a9c21b7e40
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e7a1c0de5a01"
down_revision = "f3a9c21b7e40"
branch_labels = None
depends_on = None

SUBSCRIPTION_STATUSES = ("trialing", "active", "past_due", "suspended", "canceled")


def upgrade():
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="eur"
        ),
        sa.Column(
            "monthly_price_cents", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("included_minutes", sa.Integer(), nullable=True),
        sa.Column("overage_price_cents_per_minute", sa.Integer(), nullable=True),
        sa.Column("max_concurrent_calls", sa.Integer(), nullable=True),
        sa.Column("max_agents", sa.Integer(), nullable=True),
        sa.Column("max_human_seats", sa.Integer(), nullable=True),
        sa.Column("max_campaigns", sa.Integer(), nullable=True),
        sa.Column(
            "features", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column("stripe_price_id", sa.String(length=128), nullable=True),
        sa.Column(
            "is_public", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_subscription_plans_id", "subscription_plans", ["id"])
    op.create_index(
        "ix_subscription_plans_code", "subscription_plans", ["code"], unique=True
    )

    status_enum = postgresql.ENUM(
        *SUBSCRIPTION_STATUSES, name="subscription_status", create_type=False
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "organization_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("subscription_plans.id"),
            nullable=False,
        ),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("past_due_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "limit_overrides",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("billing_email", sa.String(length=255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(length=128), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_organization_subscriptions_id", "organization_subscriptions", ["id"]
    )
    op.create_index(
        "ix_organization_subscriptions_organization_id",
        "organization_subscriptions",
        ["organization_id"],
        unique=True,
    )
    op.create_index(
        "ix_organization_subscriptions_stripe_customer_id",
        "organization_subscriptions",
        ["stripe_customer_id"],
    )
    op.create_index(
        "ix_organization_subscriptions_stripe_subscription_id",
        "organization_subscriptions",
        ["stripe_subscription_id"],
    )

    op.create_table(
        "contact_center_queues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=48), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("ring_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_wait_seconds", sa.Integer(), nullable=False),
        sa.Column("wrapup_seconds", sa.Integer(), nullable=False),
        sa.Column("announce_position", sa.Boolean(), nullable=False),
        sa.Column("overflow_destination", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "slug", name="_cc_queue_org_slug_uc"),
    )
    op.create_index("ix_contact_center_queues_id", "contact_center_queues", ["id"])

    op.create_table(
        "contact_center_agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("sip_username", sa.String(length=64), nullable=False, unique=True),
        sa.Column("sip_md5_cred", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "extension", name="_cc_agent_org_extension_uc"
        ),
    )
    op.create_index("ix_contact_center_agents_id", "contact_center_agents", ["id"])

    op.create_table(
        "contact_center_queue_members",
        sa.Column(
            "queue_id",
            sa.Integer(),
            sa.ForeignKey("contact_center_queues.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("contact_center_agents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("penalty", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_table("contact_center_queue_members")
    op.drop_index("ix_contact_center_agents_id", table_name="contact_center_agents")
    op.drop_table("contact_center_agents")
    op.drop_index("ix_contact_center_queues_id", table_name="contact_center_queues")
    op.drop_table("contact_center_queues")
    op.drop_index(
        "ix_organization_subscriptions_stripe_subscription_id",
        table_name="organization_subscriptions",
    )
    op.drop_index(
        "ix_organization_subscriptions_stripe_customer_id",
        table_name="organization_subscriptions",
    )
    op.drop_index(
        "ix_organization_subscriptions_organization_id",
        table_name="organization_subscriptions",
    )
    op.drop_index(
        "ix_organization_subscriptions_id", table_name="organization_subscriptions"
    )
    op.drop_table("organization_subscriptions")
    postgresql.ENUM(name="subscription_status").drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_subscription_plans_code", table_name="subscription_plans")
    op.drop_index("ix_subscription_plans_id", table_name="subscription_plans")
    op.drop_table("subscription_plans")

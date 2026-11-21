"""Agent actions: appointments, sent messages, tickets; new tool categories.

Also adds the ``schedule_callback`` tool category that the callbacks feature
introduced without updating the PostgreSQL enum.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""

import sqlalchemy as sa
from alembic import op
from alembic_postgresql_enum import TableReference

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None

OLD_TOOL_CATEGORIES = [
    "http_api",
    "end_call",
    "transfer_call",
    "transfer_agent",
    "calculator",
    "native",
    "integration",
    "mcp",
]
NEW_TOOL_CATEGORIES = OLD_TOOL_CATEGORIES + [
    "schedule_callback",
    "book_appointment",
    "send_message",
    "create_ticket",
]
OLD_CREDENTIAL_TYPES = [
    "none",
    "api_key",
    "bearer_token",
    "basic_auth",
    "custom_header",
]
NEW_CREDENTIAL_TYPES = OLD_CREDENTIAL_TYPES + ["service_account"]


def _sync(tool_categories, credential_types):
    op.sync_enum_values(
        enum_schema="public",
        enum_name="tool_category",
        new_values=tool_categories,
        affected_columns=[
            TableReference(
                table_schema="public", table_name="tools", column_name="category"
            )
        ],
        enum_values_to_rename=[],
    )
    op.sync_enum_values(
        enum_schema="public",
        enum_name="webhook_credential_type",
        new_values=credential_types,
        affected_columns=[
            TableReference(
                table_schema="public",
                table_name="external_credentials",
                column_name="credential_type",
            )
        ],
        enum_values_to_rename=[],
    )


def upgrade():
    _sync(NEW_TOOL_CATEGORIES, NEW_CREDENTIAL_TYPES)

    def org_fk():
        return sa.ForeignKey("organizations.id", ondelete="CASCADE")

    def run_fk():
        return sa.ForeignKey("workflow_runs.id", ondelete="SET NULL")

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), org_fk(), nullable=False),
        sa.Column("calendar_key", sa.String(length=64), nullable=False),
        sa.Column("calendar_name", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_name", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), run_fk(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_appointments_id", "appointments", ["id"])
    op.create_index(
        "ix_appointments_calendar_time",
        "appointments",
        ["organization_id", "calendar_key", "start_at"],
    )
    op.create_table(
        "sent_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), org_fk(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("tool_uuid", sa.String(length=64), nullable=True),
        sa.Column("workflow_run_id", sa.Integer(), run_fk(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sent_messages_id", "sent_messages", ["id"])
    op.create_index(
        "ix_sent_messages_org_created",
        "sent_messages",
        ["organization_id", "created_at"],
    )
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), org_fk(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("external_url", sa.String(length=512), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("customer_name", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column(
            "assigned_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("workflow_run_id", sa.Integer(), run_fk(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "number", name="uq_tickets_org_number"),
    )
    op.create_index("ix_tickets_id", "tickets", ["id"])
    op.create_index("ix_tickets_org_status", "tickets", ["organization_id", "status"])


def downgrade():
    op.drop_table("tickets")
    op.drop_table("sent_messages")
    op.drop_table("appointments")
    _sync(
        [c for c in OLD_TOOL_CATEGORIES],
        OLD_CREDENTIAL_TYPES,
    )

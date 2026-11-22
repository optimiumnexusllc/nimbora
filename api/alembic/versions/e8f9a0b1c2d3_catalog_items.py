"""Catalog: products, properties, rooms… searched by the agents

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-11-22 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from alembic_postgresql_enum import TableReference

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TOOL_CATEGORIES = [
    "http_api",
    "end_call",
    "transfer_call",
    "transfer_agent",
    "calculator",
    "native",
    "integration",
    "mcp",
    "schedule_callback",
    "book_appointment",
    "send_message",
    "create_ticket",
]


def _sync_tool_categories(values: list[str]) -> None:
    op.sync_enum_values(
        enum_schema="public",
        enum_name="tool_category",
        new_values=values,
        affected_columns=[
            TableReference(
                table_schema="public", table_name="tools", column_name="category"
            )
        ],
        enum_values_to_rename=[],
    )


def upgrade() -> None:
    _sync_tool_categories(TOOL_CATEGORIES + ["search_catalog"])
    op.create_table(
        "catalog_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False, server_default="product"),
        sa.Column("sku", sa.String(64), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("price_cents", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="XOF"),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "sku", name="_catalog_org_sku_uc"),
    )
    op.create_index("ix_catalog_items_id", "catalog_items", ["id"])
    op.create_index(
        "ix_catalog_items_org_kind", "catalog_items", ["organization_id", "kind"]
    )
    op.create_index(
        "ix_catalog_items_org_category",
        "catalog_items",
        ["organization_id", "category"],
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_items_org_category", table_name="catalog_items")
    op.drop_index("ix_catalog_items_org_kind", table_name="catalog_items")
    op.drop_index("ix_catalog_items_id", table_name="catalog_items")
    op.drop_table("catalog_items")
    op.execute("DELETE FROM tools WHERE category = 'search_catalog'")
    _sync_tool_categories(TOOL_CATEGORIES)

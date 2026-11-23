"""Agent tests against simulated customers

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-11-23 09:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_tests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("persona", sa.Text(), nullable=False),
        sa.Column("opening", sa.String(length=500), nullable=True),
        sa.Column("success_criteria", sa.JSON(), nullable=False),
        sa.Column("must_call", sa.JSON(), nullable=False),
        sa.Column("must_not_call", sa.JSON(), nullable=False),
        sa.Column("forbidden_phrases", sa.JSON(), nullable=False),
        sa.Column("mock_results", sa.JSON(), nullable=False),
        sa.Column("initial_context", sa.JSON(), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_tests_id"), "agent_tests", ["id"])
    op.create_index(
        "ix_agent_tests_org_workflow", "agent_tests", ["organization_id", "workflow_id"]
    )
    op.create_table(
        "agent_test_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=16), nullable=False),
        sa.Column("definition_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("started_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["test_id"], ["agent_tests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["started_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_test_runs_id"), "agent_test_runs", ["id"])
    op.create_index(
        "ix_agent_test_runs_test_created", "agent_test_runs", ["test_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("agent_test_runs")
    op.drop_table("agent_tests")

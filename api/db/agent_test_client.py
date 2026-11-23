"""Database access for agent tests (simulated customers), per organization."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import AgentTestModel, AgentTestRunModel


class AgentTestClient(BaseDBClient):
    async def list_agent_tests(
        self, organization_id: int, workflow_id: int
    ) -> list[AgentTestModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(AgentTestModel)
                .where(
                    AgentTestModel.organization_id == organization_id,
                    AgentTestModel.workflow_id == workflow_id,
                )
                .order_by(AgentTestModel.id)
            )
            return list(result.scalars().all())

    async def get_agent_test(
        self, organization_id: int, test_id: int
    ) -> AgentTestModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(AgentTestModel).where(
                    AgentTestModel.id == test_id,
                    AgentTestModel.organization_id == organization_id,
                )
            )
            return result.scalars().first()

    async def save_agent_test(
        self,
        organization_id: int,
        workflow_id: int,
        values: dict[str, Any],
        test_id: int | None = None,
    ) -> AgentTestModel | None:
        async with self.async_session() as session:
            if test_id is None:
                row = AgentTestModel(
                    organization_id=organization_id, workflow_id=workflow_id
                )
                session.add(row)
            else:
                row = (
                    (
                        await session.execute(
                            select(AgentTestModel).where(
                                AgentTestModel.id == test_id,
                                AgentTestModel.organization_id == organization_id,
                                AgentTestModel.workflow_id == workflow_id,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if row is None:
                    return None
            for key, value in values.items():
                setattr(row, key, value)
            await session.commit()
            await session.refresh(row)
            return row

    async def delete_agent_test(
        self, organization_id: int, workflow_id: int, test_id: int
    ) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                delete(AgentTestModel).where(
                    AgentTestModel.id == test_id,
                    AgentTestModel.organization_id == organization_id,
                    AgentTestModel.workflow_id == workflow_id,
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def create_agent_test_run(self, values: dict[str, Any]) -> AgentTestRunModel:
        async with self.async_session() as session:
            row = AgentTestRunModel(**values)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def update_agent_test_run(self, run_id: int, values: dict[str, Any]) -> None:
        async with self.async_session() as session:
            row = await session.get(AgentTestRunModel, run_id)
            if row is None:
                return
            for key, value in values.items():
                setattr(row, key, value)
            if values.get("status") in {"passed", "failed", "error"}:
                row.finished_at = datetime.now(UTC)
            await session.commit()

    async def get_agent_test_run(
        self, organization_id: int, run_id: int
    ) -> AgentTestRunModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(AgentTestRunModel).where(
                    AgentTestRunModel.id == run_id,
                    AgentTestRunModel.organization_id == organization_id,
                )
            )
            return result.scalars().first()

    async def list_agent_test_runs(
        self, organization_id: int, test_id: int, limit: int = 20
    ) -> list[AgentTestRunModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(AgentTestRunModel)
                .where(
                    AgentTestRunModel.organization_id == organization_id,
                    AgentTestRunModel.test_id == test_id,
                )
                .order_by(AgentTestRunModel.id.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def latest_agent_test_runs(
        self, organization_id: int, workflow_id: int
    ) -> dict[int, AgentTestRunModel]:
        """The last run of each test of a workflow."""
        async with self.async_session() as session:
            last = (
                select(func.max(AgentTestRunModel.id))
                .where(
                    AgentTestRunModel.organization_id == organization_id,
                    AgentTestRunModel.workflow_id == workflow_id,
                )
                .group_by(AgentTestRunModel.test_id)
            )
            result = await session.execute(
                select(AgentTestRunModel).where(AgentTestRunModel.id.in_(last))
            )
            return {row.test_id: row for row in result.scalars().all()}

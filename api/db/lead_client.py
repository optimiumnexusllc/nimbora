"""Database access for leads. Every query is filtered by organization."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import LeadModel

LEAD_FIELDS = {
    "customer_id",
    "name",
    "phone",
    "email",
    "company",
    "need",
    "budget_min",
    "budget_max",
    "currency",
    "timeline",
    "decision_maker",
    "interests",
    "stage",
    "score",
    "source",
    "owner",
    "notes",
    "lost_reason",
    "next_action",
    "next_action_at",
    "workflow_run_id",
    "closed_at",
}
OPEN_STAGES = ("new", "qualified", "proposal", "negotiation")


class LeadClient(BaseDBClient):
    async def list_leads(
        self,
        organization_id: int,
        *,
        stage: str | None = None,
        search: str | None = None,
        limit: int = 500,
    ) -> list[LeadModel]:
        conditions = [LeadModel.organization_id == organization_id]
        if stage:
            conditions.append(LeadModel.stage == stage)
        if search:
            like = f"%{search}%"
            conditions.append(
                or_(
                    LeadModel.name.ilike(like),
                    LeadModel.phone.ilike(like),
                    LeadModel.email.ilike(like),
                    LeadModel.company.ilike(like),
                    LeadModel.need.ilike(like),
                )
            )
        async with self.async_session() as session:
            rows = await session.execute(
                select(LeadModel)
                .where(and_(*conditions))
                .order_by(LeadModel.score.desc(), LeadModel.updated_at.desc())
                .limit(limit)
            )
            return list(rows.scalars())

    async def get_lead(self, organization_id: int, lead_id: int) -> LeadModel | None:
        async with self.async_session() as session:
            return (
                await session.execute(
                    select(LeadModel).where(
                        LeadModel.organization_id == organization_id,
                        LeadModel.id == lead_id,
                    )
                )
            ).scalar_one_or_none()

    async def find_open_lead_by_phone(
        self, organization_id: int, phone: str
    ) -> LeadModel | None:
        async with self.async_session() as session:
            return (
                await session.execute(
                    select(LeadModel)
                    .where(
                        LeadModel.organization_id == organization_id,
                        LeadModel.phone == phone,
                        LeadModel.stage.in_(OPEN_STAGES),
                    )
                    .order_by(LeadModel.updated_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def create_lead(
        self, organization_id: int, fields: dict[str, Any]
    ) -> LeadModel:
        async with self.async_session() as session:
            lead = LeadModel(
                organization_id=organization_id,
                **{k: v for k, v in fields.items() if k in LEAD_FIELDS},
            )
            session.add(lead)
            await session.commit()
            await session.refresh(lead)
            return lead

    async def update_lead(
        self, organization_id: int, lead_id: int, fields: dict[str, Any]
    ) -> LeadModel | None:
        async with self.async_session() as session:
            lead = (
                await session.execute(
                    select(LeadModel).where(
                        LeadModel.organization_id == organization_id,
                        LeadModel.id == lead_id,
                    )
                )
            ).scalar_one_or_none()
            if lead is None:
                return None
            for key, value in fields.items():
                if key in LEAD_FIELDS:
                    setattr(lead, key, value)
            lead.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(lead)
            return lead

    async def delete_lead(self, organization_id: int, lead_id: int) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                delete(LeadModel).where(
                    LeadModel.organization_id == organization_id,
                    LeadModel.id == lead_id,
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def lead_pipeline(self, organization_id: int) -> list[dict[str, Any]]:
        """Per stage: how many leads, and the sum of their maximum budgets."""
        async with self.async_session() as session:
            rows = await session.execute(
                select(
                    LeadModel.stage,
                    LeadModel.currency,
                    func.count(),
                    func.coalesce(func.sum(LeadModel.budget_max), 0),
                )
                .where(LeadModel.organization_id == organization_id)
                .group_by(LeadModel.stage, LeadModel.currency)
            )
            return [
                {"stage": s, "currency": c, "count": int(n), "budget": int(b)}
                for s, c, n, b in rows
            ]

"""Database access for the enterprise SaaS layer (plans and subscriptions)."""

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    HumanCallUsageModel,
    OrganizationModel,
    OrganizationSubscriptionModel,
    SubscriptionPlanModel,
    UserModel,
    WorkflowModel,
    WorkflowRunModel,
    organization_users_association,
)

# Columns an operator may set on a plan through the admin API.
PLAN_MUTABLE_FIELDS = {
    "name",
    "description",
    "currency",
    "monthly_price_cents",
    "included_minutes",
    "overage_price_cents_per_minute",
    "included_human_minutes",
    "human_overage_price_cents_per_minute",
    "max_concurrent_calls",
    "max_agents",
    "max_human_seats",
    "max_campaigns",
    "features",
    "stripe_price_id",
    "is_public",
    "is_active",
    "sort_order",
}

SUBSCRIPTION_MUTABLE_FIELDS = {
    "plan_id",
    "status",
    "current_period_start",
    "current_period_end",
    "trial_ends_at",
    "past_due_since",
    "limit_overrides",
    "company_name",
    "billing_email",
    "stripe_customer_id",
    "stripe_subscription_id",
    "notes",
}


class SaasClient(BaseDBClient):
    # ------------------------------------------------------------------ plans
    async def list_subscription_plans(
        self, *, public_only: bool = False, include_inactive: bool = False
    ) -> list[SubscriptionPlanModel]:
        async with self.async_session() as session:
            query = select(SubscriptionPlanModel)
            if public_only:
                query = query.where(SubscriptionPlanModel.is_public.is_(True))
            if not include_inactive:
                query = query.where(SubscriptionPlanModel.is_active.is_(True))
            query = query.order_by(
                SubscriptionPlanModel.sort_order, SubscriptionPlanModel.id
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_subscription_plan_by_code(
        self, code: str
    ) -> SubscriptionPlanModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(SubscriptionPlanModel).where(SubscriptionPlanModel.code == code)
            )
            return result.scalars().first()

    async def get_subscription_plan_by_id(
        self, plan_id: int
    ) -> SubscriptionPlanModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(SubscriptionPlanModel).where(SubscriptionPlanModel.id == plan_id)
            )
            return result.scalars().first()

    async def get_subscription_plan_by_stripe_price(
        self, stripe_price_id: str
    ) -> SubscriptionPlanModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(SubscriptionPlanModel).where(
                    SubscriptionPlanModel.stripe_price_id == stripe_price_id
                )
            )
            return result.scalars().first()

    async def insert_subscription_plan_if_missing(
        self, code: str, fields: dict[str, Any]
    ) -> None:
        """Seed a plan without overwriting operator edits to an existing one."""
        values = {k: v for k, v in fields.items() if k in PLAN_MUTABLE_FIELDS}
        async with self.async_session() as session:
            await session.execute(
                insert(SubscriptionPlanModel)
                .values(code=code, **values)
                .on_conflict_do_nothing(index_elements=["code"])
            )
            await session.commit()

    async def upsert_subscription_plan(
        self, code: str, fields: dict[str, Any]
    ) -> SubscriptionPlanModel:
        values = {k: v for k, v in fields.items() if k in PLAN_MUTABLE_FIELDS}
        async with self.async_session() as session:
            stmt = insert(SubscriptionPlanModel).values(code=code, **values)
            if values:
                stmt = stmt.on_conflict_do_update(index_elements=["code"], set_=values)
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=["code"])
            await session.execute(stmt)
            await session.commit()
        plan = await self.get_subscription_plan_by_code(code)
        assert plan is not None
        return plan

    # ---------------------------------------------------------- subscriptions
    async def get_organization_subscription(
        self, organization_id: int
    ) -> OrganizationSubscriptionModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationSubscriptionModel).where(
                    OrganizationSubscriptionModel.organization_id == organization_id
                )
            )
            return result.scalars().first()

    async def create_organization_subscription_if_missing(
        self,
        *,
        organization_id: int,
        plan_id: int,
        status: str,
        current_period_start: datetime,
        current_period_end: datetime,
        trial_ends_at: datetime | None = None,
        billing_email: str | None = None,
    ) -> OrganizationSubscriptionModel:
        """Idempotent: concurrent first requests create exactly one row."""
        async with self.async_session() as session:
            await session.execute(
                insert(OrganizationSubscriptionModel)
                .values(
                    organization_id=organization_id,
                    plan_id=plan_id,
                    status=status,
                    current_period_start=current_period_start,
                    current_period_end=current_period_end,
                    trial_ends_at=trial_ends_at,
                    billing_email=billing_email,
                    limit_overrides={},
                )
                .on_conflict_do_nothing(index_elements=["organization_id"])
            )
            await session.commit()
        subscription = await self.get_organization_subscription(organization_id)
        assert subscription is not None
        return subscription

    async def update_organization_subscription(
        self, organization_id: int, fields: dict[str, Any]
    ) -> OrganizationSubscriptionModel | None:
        values = {k: v for k, v in fields.items() if k in SUBSCRIPTION_MUTABLE_FIELDS}
        if values:
            async with self.async_session() as session:
                await session.execute(
                    update(OrganizationSubscriptionModel)
                    .where(
                        OrganizationSubscriptionModel.organization_id == organization_id
                    )
                    .values(**values, updated_at=func.now())
                )
                await session.commit()
        return await self.get_organization_subscription(organization_id)

    async def find_organization_subscription_by_stripe(
        self,
        *,
        customer_id: str | None = None,
        subscription_id: str | None = None,
    ) -> OrganizationSubscriptionModel | None:
        conditions = []
        if subscription_id:
            conditions.append(
                OrganizationSubscriptionModel.stripe_subscription_id == subscription_id
            )
        if customer_id:
            conditions.append(
                OrganizationSubscriptionModel.stripe_customer_id == customer_id
            )
        if not conditions:
            return None
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationSubscriptionModel).where(or_(*conditions))
            )
            return result.scalars().first()

    async def list_organization_subscriptions(
        self, *, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> tuple[list[OrganizationSubscriptionModel], int]:
        async with self.async_session() as session:
            query = select(OrganizationSubscriptionModel)
            count_query = select(func.count(OrganizationSubscriptionModel.id))
            if status:
                query = query.where(OrganizationSubscriptionModel.status == status)
                count_query = count_query.where(
                    OrganizationSubscriptionModel.status == status
                )
            query = (
                query.order_by(OrganizationSubscriptionModel.id.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = (await session.execute(query)).scalars().all()
            total = (await session.execute(count_query)).scalar_one()
            return list(rows), int(total)

    async def list_organization_member_emails(
        self, organization_ids: list[int]
    ) -> dict[int, list[str]]:
        if not organization_ids:
            return {}
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    organization_users_association.c.organization_id, UserModel.email
                )
                .join(
                    UserModel,
                    UserModel.id == organization_users_association.c.user_id,
                )
                .where(
                    organization_users_association.c.organization_id.in_(
                        organization_ids
                    )
                )
            )
            emails: dict[int, list[str]] = {}
            for org_id, email in result.all():
                if email:
                    emails.setdefault(org_id, []).append(email)
            return emails

    async def list_organizations_without_subscription(self) -> list[int]:
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationModel.id)
                .outerjoin(
                    OrganizationSubscriptionModel,
                    OrganizationSubscriptionModel.organization_id
                    == OrganizationModel.id,
                )
                .where(OrganizationSubscriptionModel.id.is_(None))
            )
            return [row[0] for row in result.all()]

    # ------------------------------------------------------------------ usage
    async def get_organization_billable_seconds(
        self, organization_id: int, start: datetime, end: datetime
    ) -> float:
        """Seconds of completed calls in [start, end) for one organization."""
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            WorkflowRunModel.usage_info[
                                "call_duration_seconds"
                            ].as_float()
                        ),
                        0.0,
                    )
                )
                .join(WorkflowModel, WorkflowModel.id == WorkflowRunModel.workflow_id)
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowRunModel.created_at >= start,
                    WorkflowRunModel.created_at < end,
                )
            )
            return float(result.scalar_one() or 0.0)

    async def record_human_call_usage(
        self, organization_id: int, fields: dict[str, Any]
    ) -> bool:
        """Insert one billable human call; False if already counted."""
        async with self.async_session() as session:
            result = await session.execute(
                insert(HumanCallUsageModel)
                .values(organization_id=organization_id, **fields)
                .on_conflict_do_nothing(constraint="uq_human_call_usage_ext")
                .returning(HumanCallUsageModel.id)
            )
            await session.commit()
            return result.scalar_one_or_none() is not None

    async def get_organization_human_seconds(
        self, organization_id: int, start: datetime, end: datetime
    ) -> float:
        """Billable seconds of human calls started in [start, end)."""
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    func.coalesce(func.sum(HumanCallUsageModel.billable_seconds), 0)
                ).where(
                    HumanCallUsageModel.organization_id == organization_id,
                    HumanCallUsageModel.started_at >= start,
                    HumanCallUsageModel.started_at < end,
                )
            )
            return float(result.scalar_one() or 0)

    async def get_usage_by_organization(
        self, start: datetime, end: datetime
    ) -> dict[int, dict[str, float]]:
        """AI and human seconds of every organization in [start, end)."""
        usage: dict[int, dict[str, float]] = {}
        async with self.async_session() as session:
            ai = await session.execute(
                select(
                    WorkflowModel.organization_id,
                    func.coalesce(
                        func.sum(
                            WorkflowRunModel.usage_info[
                                "call_duration_seconds"
                            ].as_float()
                        ),
                        0.0,
                    ),
                )
                .join(WorkflowModel, WorkflowModel.id == WorkflowRunModel.workflow_id)
                .where(
                    WorkflowRunModel.created_at >= start,
                    WorkflowRunModel.created_at < end,
                )
                .group_by(WorkflowModel.organization_id)
            )
            for organization_id, seconds in ai.all():
                usage.setdefault(organization_id, {"ai": 0.0, "human": 0.0})["ai"] = (
                    float(seconds or 0)
                )
            human = await session.execute(
                select(
                    HumanCallUsageModel.organization_id,
                    func.sum(HumanCallUsageModel.billable_seconds),
                )
                .where(
                    HumanCallUsageModel.started_at >= start,
                    HumanCallUsageModel.started_at < end,
                )
                .group_by(HumanCallUsageModel.organization_id)
            )
            for organization_id, seconds in human.all():
                usage.setdefault(organization_id, {"ai": 0.0, "human": 0.0})[
                    "human"
                ] = float(seconds or 0)
        return usage

    async def count_organization_agents(self, organization_id: int) -> int:
        """Active (non-archived) AI agents (workflows) of one organization."""
        async with self.async_session() as session:
            result = await session.execute(
                select(func.count(WorkflowModel.id)).where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowModel.status != "archived",
                )
            )
            return int(result.scalar_one())

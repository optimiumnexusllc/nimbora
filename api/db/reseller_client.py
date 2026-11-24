"""Database access for resellers, their offers and companies, and invitations."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    InvitationModel,
    OrganizationModel,
    OrganizationSubscriptionModel,
    ResellerMemberModel,
    ResellerModel,
    SubscriptionPlanModel,
)

RESELLER_MUTABLE_FIELDS = {"name", "contact_email", "commission_bps", "is_active"}
RESELLER_PLAN_FIELDS = {
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
    "base_plan_id",
}


class ResellerClient(BaseDBClient):
    # ------------------------------------------------------------ resellers
    async def create_reseller(self, **fields: Any) -> ResellerModel:
        values = {k: v for k, v in fields.items() if k in RESELLER_MUTABLE_FIELDS}
        async with self.async_session() as session:
            reseller = ResellerModel(**values)
            session.add(reseller)
            await session.commit()
            await session.refresh(reseller)
            return reseller

    async def get_reseller(self, reseller_id: int) -> ResellerModel | None:
        async with self.async_session() as session:
            return await session.get(ResellerModel, reseller_id)

    async def update_reseller(
        self, reseller_id: int, fields: dict[str, Any]
    ) -> ResellerModel | None:
        values = {k: v for k, v in fields.items() if k in RESELLER_MUTABLE_FIELDS}
        if values:
            async with self.async_session() as session:
                await session.execute(
                    update(ResellerModel)
                    .where(ResellerModel.id == reseller_id)
                    .values(**values)
                )
                await session.commit()
        return await self.get_reseller(reseller_id)

    async def list_resellers_with_counts(self) -> list[tuple[ResellerModel, int]]:
        async with self.async_session() as session:
            companies = (
                select(
                    OrganizationModel.reseller_id,
                    func.count(OrganizationModel.id).label("n"),
                )
                .where(OrganizationModel.reseller_id.is_not(None))
                .group_by(OrganizationModel.reseller_id)
                .subquery()
            )
            result = await session.execute(
                select(ResellerModel, func.coalesce(companies.c.n, 0))
                .outerjoin(companies, companies.c.reseller_id == ResellerModel.id)
                .order_by(ResellerModel.name, ResellerModel.id)
            )
            return [(row[0], int(row[1])) for row in result.all()]

    async def set_reseller_stripe(
        self, reseller_id: int, account_id: str, charges_enabled: bool
    ) -> None:
        async with self.async_session() as session:
            await session.execute(
                update(ResellerModel)
                .where(ResellerModel.id == reseller_id)
                .values(
                    stripe_account_id=account_id,
                    stripe_charges_enabled=charges_enabled,
                )
            )
            await session.commit()

    async def get_reseller_by_stripe_account(
        self, account_id: str
    ) -> ResellerModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(ResellerModel).where(
                    ResellerModel.stripe_account_id == account_id
                )
            )
            return result.scalars().first()

    async def count_reseller_companies(self, reseller_id: int) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                select(func.count(OrganizationModel.id)).where(
                    OrganizationModel.reseller_id == reseller_id
                )
            )
            return int(result.scalar_one())

    async def add_reseller_member(self, reseller_id: int, user_id: int) -> None:
        from sqlalchemy.dialects.postgresql import insert

        async with self.async_session() as session:
            await session.execute(
                insert(ResellerMemberModel)
                .values(reseller_id=reseller_id, user_id=user_id)
                .on_conflict_do_nothing(constraint="uq_reseller_member")
            )
            await session.commit()

    async def get_active_reseller_of_user(self, user_id: int) -> ResellerModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(ResellerModel)
                .join(
                    ResellerMemberModel,
                    ResellerMemberModel.reseller_id == ResellerModel.id,
                )
                .where(
                    ResellerMemberModel.user_id == user_id,
                    ResellerModel.is_active.is_(True),
                )
                .order_by(ResellerModel.id)
            )
            return result.scalars().first()

    # --------------------------------------------------------------- offers
    async def list_reseller_plans(
        self, reseller_id: int
    ) -> list[SubscriptionPlanModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(SubscriptionPlanModel)
                .where(SubscriptionPlanModel.reseller_id == reseller_id)
                .order_by(SubscriptionPlanModel.sort_order, SubscriptionPlanModel.id)
            )
            return list(result.scalars().all())

    async def list_platform_plans(self) -> list[SubscriptionPlanModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(SubscriptionPlanModel)
                .where(
                    SubscriptionPlanModel.reseller_id.is_(None),
                    SubscriptionPlanModel.is_active.is_(True),
                )
                .order_by(SubscriptionPlanModel.sort_order, SubscriptionPlanModel.id)
            )
            return list(result.scalars().all())

    async def get_reseller_plan(
        self, reseller_id: int, code: str
    ) -> SubscriptionPlanModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(SubscriptionPlanModel).where(
                    SubscriptionPlanModel.reseller_id == reseller_id,
                    SubscriptionPlanModel.code == code,
                )
            )
            return result.scalars().first()

    async def create_reseller_plan(
        self, reseller_id: int, code: str, fields: dict[str, Any]
    ) -> SubscriptionPlanModel:
        values = {k: v for k, v in fields.items() if k in RESELLER_PLAN_FIELDS}
        async with self.async_session() as session:
            plan = SubscriptionPlanModel(
                code=code,
                reseller_id=reseller_id,
                is_public=False,
                is_active=True,
                **values,
            )
            session.add(plan)
            await session.commit()
            await session.refresh(plan)
            return plan

    async def update_reseller_plan(
        self, reseller_id: int, code: str, fields: dict[str, Any]
    ) -> SubscriptionPlanModel | None:
        values = {k: v for k, v in fields.items() if k in RESELLER_PLAN_FIELDS}
        async with self.async_session() as session:
            await session.execute(
                update(SubscriptionPlanModel)
                .where(
                    SubscriptionPlanModel.reseller_id == reseller_id,
                    SubscriptionPlanModel.code == code,
                )
                .values(**values)
            )
            await session.commit()
        return await self.get_reseller_plan(reseller_id, code)

    # ------------------------------------------------------------ companies
    async def set_organization_reseller(
        self, organization_id: int, reseller_id: int | None
    ) -> None:
        async with self.async_session() as session:
            await session.execute(
                update(OrganizationModel)
                .where(OrganizationModel.id == organization_id)
                .values(reseller_id=reseller_id)
            )
            await session.commit()

    async def list_reseller_companies(
        self, reseller_id: int
    ) -> list[tuple[OrganizationModel, OrganizationSubscriptionModel | None]]:
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationModel, OrganizationSubscriptionModel)
                .outerjoin(
                    OrganizationSubscriptionModel,
                    OrganizationSubscriptionModel.organization_id
                    == OrganizationModel.id,
                )
                .where(OrganizationModel.reseller_id == reseller_id)
                .order_by(OrganizationModel.id.desc())
            )
            return [(row[0], row[1]) for row in result.all()]

    async def get_reseller_company(
        self, reseller_id: int, organization_id: int
    ) -> OrganizationModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationModel).where(
                    OrganizationModel.id == organization_id,
                    OrganizationModel.reseller_id == reseller_id,
                )
            )
            return result.scalars().first()

    # ---------------------------------------------------------- invitations
    async def create_invitation(self, **fields: Any) -> InvitationModel:
        async with self.async_session() as session:
            invitation = InvitationModel(**fields)
            session.add(invitation)
            await session.commit()
            await session.refresh(invitation)
            return invitation

    async def get_invitation_by_hash(self, token_hash: str) -> InvitationModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(InvitationModel).where(InvitationModel.token_hash == token_hash)
            )
            return result.scalars().first()

    async def claim_invitation(self, invitation_id: int) -> bool:
        """Mark it used; False if it already was (one use, even concurrently)."""
        async with self.async_session() as session:
            result = await session.execute(
                update(InvitationModel)
                .where(
                    InvitationModel.id == invitation_id,
                    InvitationModel.accepted_at.is_(None),
                )
                .values(accepted_at=datetime.now(UTC))
            )
            await session.commit()
            return result.rowcount == 1

"""Database access for customer memory (profiles and their call history).

Every query is filtered by ``organization_id``: a caller known to one company
is a stranger to every other company on the platform.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import CustomerInteractionModel, CustomerProfileModel

PROFILE_MUTABLE_FIELDS = {"name", "notes", "tags", "attributes"}


class CustomerMemoryClient(BaseDBClient):
    async def find_customer_profile(
        self, organization_id: int, phone: str, phone_suffix: str
    ) -> CustomerProfileModel | None:
        """Exact number first, then the same last 9 digits (local vs +intl)."""
        async with self.async_session() as session:
            result = await session.execute(
                select(CustomerProfileModel)
                .where(
                    CustomerProfileModel.organization_id == organization_id,
                    or_(
                        CustomerProfileModel.phone == phone,
                        CustomerProfileModel.phone_suffix == phone_suffix,
                    ),
                )
                .order_by(
                    (CustomerProfileModel.phone == phone).desc(),
                    CustomerProfileModel.last_seen_at.desc(),
                )
                .limit(1)
            )
            return result.scalars().first()

    async def get_customer_profile(
        self, organization_id: int, customer_id: int
    ) -> CustomerProfileModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(CustomerProfileModel).where(
                    CustomerProfileModel.organization_id == organization_id,
                    CustomerProfileModel.id == customer_id,
                )
            )
            return result.scalars().first()

    async def get_or_create_customer_profile(
        self, organization_id: int, phone: str, phone_suffix: str
    ) -> CustomerProfileModel:
        existing = await self.find_customer_profile(
            organization_id, phone, phone_suffix
        )
        if existing is not None:
            return existing
        async with self.async_session() as session:
            await session.execute(
                insert(CustomerProfileModel)
                .values(
                    organization_id=organization_id,
                    phone=phone,
                    phone_suffix=phone_suffix,
                    tags=[],
                    attributes={},
                    total_calls=0,
                    first_seen_at=datetime.now(UTC),
                    last_seen_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(constraint="_customer_org_phone_uc")
            )
            await session.commit()
        profile = await self.find_customer_profile(organization_id, phone, phone_suffix)
        assert profile is not None
        return profile

    async def update_customer_profile(
        self, organization_id: int, customer_id: int, fields: dict[str, Any]
    ) -> CustomerProfileModel | None:
        allowed = PROFILE_MUTABLE_FIELDS | {
            "last_summary",
            "last_sentiment",
            "last_seen_at",
        }
        values = {k: v for k, v in fields.items() if k in allowed}
        if values:
            async with self.async_session() as session:
                await session.execute(
                    update(CustomerProfileModel)
                    .where(
                        CustomerProfileModel.organization_id == organization_id,
                        CustomerProfileModel.id == customer_id,
                    )
                    .values(**values)
                )
                await session.commit()
        return await self.get_customer_profile(organization_id, customer_id)

    async def record_customer_interaction(
        self,
        organization_id: int,
        customer_id: int,
        *,
        workflow_run_id: int | None,
        fields: dict[str, Any],
    ) -> bool:
        """Add one interaction (idempotent per run) and bump the call counter.

        Returns False when this run was already recorded (task retried).
        """
        async with self.async_session() as session:
            result = await session.execute(
                insert(CustomerInteractionModel)
                .values(
                    organization_id=organization_id,
                    customer_id=customer_id,
                    workflow_run_id=workflow_run_id,
                    created_at=datetime.now(UTC),
                    **fields,
                )
                .on_conflict_do_nothing(constraint="_customer_interaction_run_uc")
                .returning(CustomerInteractionModel.id)
            )
            inserted = result.first() is not None
            if inserted:
                await session.execute(
                    update(CustomerProfileModel)
                    .where(
                        CustomerProfileModel.organization_id == organization_id,
                        CustomerProfileModel.id == customer_id,
                    )
                    .values(
                        total_calls=CustomerProfileModel.total_calls + 1,
                        last_seen_at=datetime.now(UTC),
                    )
                )
            await session.commit()
            return inserted

    async def list_customer_interactions(
        self, organization_id: int, customer_id: int, limit: int = 20
    ) -> list[CustomerInteractionModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(CustomerInteractionModel)
                .where(
                    CustomerInteractionModel.organization_id == organization_id,
                    CustomerInteractionModel.customer_id == customer_id,
                )
                .order_by(CustomerInteractionModel.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def search_customer_profiles(
        self,
        organization_id: int,
        *,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CustomerProfileModel], int]:
        async with self.async_session() as session:
            conditions = [CustomerProfileModel.organization_id == organization_id]
            if query:
                like = f"%{query.strip()}%"
                conditions.append(
                    or_(
                        CustomerProfileModel.name.ilike(like),
                        CustomerProfileModel.phone.ilike(like),
                        CustomerProfileModel.notes.ilike(like),
                    )
                )
            rows = await session.execute(
                select(CustomerProfileModel)
                .where(*conditions)
                .order_by(CustomerProfileModel.last_seen_at.desc())
                .limit(limit)
                .offset(offset)
            )
            total = await session.execute(
                select(func.count(CustomerProfileModel.id)).where(*conditions)
            )
            return list(rows.scalars().all()), int(total.scalar_one())

    async def delete_customer_profile(
        self, organization_id: int, customer_id: int
    ) -> bool:
        """Right to be forgotten: the profile and its whole history go."""
        async with self.async_session() as session:
            await session.execute(
                delete(CustomerInteractionModel).where(
                    CustomerInteractionModel.organization_id == organization_id,
                    CustomerInteractionModel.customer_id == customer_id,
                )
            )
            result = await session.execute(
                delete(CustomerProfileModel).where(
                    CustomerProfileModel.organization_id == organization_id,
                    CustomerProfileModel.id == customer_id,
                )
            )
            await session.commit()
            return result.rowcount > 0

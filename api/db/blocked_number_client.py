"""Data access for the organization's blocked numbers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from api.db.base_client import BaseDBClient
from api.db.models import BlockedNumberModel


class BlockedNumberClient(BaseDBClient):
    async def list_blocked_numbers(
        self, organization_id: int, *, search: str | None = None, limit: int = 500
    ) -> list[BlockedNumberModel]:
        async with self.async_session() as session:
            query = select(BlockedNumberModel).where(
                BlockedNumberModel.organization_id == organization_id
            )
            if search:
                query = query.where(
                    or_(
                        BlockedNumberModel.number.contains(search),
                        BlockedNumberModel.reason.ilike(f"%{search}%"),
                    )
                )
            result = await session.execute(
                query.order_by(BlockedNumberModel.created_at.desc()).limit(limit)
            )
            return list(result.scalars().all())

    async def count_blocked_numbers(self, organization_id: int) -> int:
        from sqlalchemy import func

        async with self.async_session() as session:
            result = await session.execute(
                select(func.count(BlockedNumberModel.id)).where(
                    BlockedNumberModel.organization_id == organization_id
                )
            )
            return int(result.scalar() or 0)

    async def blocked_number_stats(self, organization_id: int) -> dict[str, int]:
        from sqlalchemy import case, func

        async with self.async_session() as session:
            result = await session.execute(
                select(
                    func.count(BlockedNumberModel.id),
                    func.coalesce(func.sum(BlockedNumberModel.hits), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                (BlockedNumberModel.source == "caller_request", 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(BlockedNumberModel.organization_id == organization_id)
            )
            total, hits, requests = result.one()
            return {
                "total": int(total or 0),
                "hits": int(hits or 0),
                "caller_requests": int(requests or 0),
            }

    async def find_blocked_number(
        self, organization_id: int, numbers: list[str], directions: list[str]
    ) -> BlockedNumberModel | None:
        """The first active entry for any spelling of the number."""
        now = datetime.now(UTC)
        async with self.async_session() as session:
            result = await session.execute(
                select(BlockedNumberModel).where(
                    BlockedNumberModel.organization_id == organization_id,
                    BlockedNumberModel.number.in_(numbers),
                    BlockedNumberModel.direction.in_(directions),
                    or_(
                        BlockedNumberModel.expires_at.is_(None),
                        BlockedNumberModel.expires_at > now,
                    ),
                )
            )
            return result.scalars().first()

    async def upsert_blocked_number(
        self, organization_id: int, number: str, fields: dict[str, Any]
    ) -> BlockedNumberModel:
        values = {
            "organization_id": organization_id,
            "number": number,
            "created_at": datetime.now(UTC),
            **fields,
        }
        updatable = {k: v for k, v in fields.items() if k != "created_by_user_id"}
        async with self.async_session() as session:
            statement = (
                insert(BlockedNumberModel)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_blocked_numbers_org_number",
                    set_=updatable or {"number": number},
                )
            )
            await session.execute(statement)
            await session.commit()
            result = await session.execute(
                select(BlockedNumberModel).where(
                    BlockedNumberModel.organization_id == organization_id,
                    BlockedNumberModel.number == number,
                )
            )
            return result.scalars().one()

    async def delete_blocked_number(self, organization_id: int, entry_id: int) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                delete(BlockedNumberModel).where(
                    BlockedNumberModel.id == entry_id,
                    BlockedNumberModel.organization_id == organization_id,
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def record_blocked_hit(self, organization_id: int, entry_id: int) -> None:
        async with self.async_session() as session:
            await session.execute(
                update(BlockedNumberModel)
                .where(
                    BlockedNumberModel.id == entry_id,
                    BlockedNumberModel.organization_id == organization_id,
                )
                .values(hits=BlockedNumberModel.hits + 1, last_hit_at=datetime.now(UTC))
            )
            await session.commit()

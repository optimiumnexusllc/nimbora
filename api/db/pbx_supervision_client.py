"""Data access for the log of PBX supervision sessions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from api.db.base_client import BaseDBClient
from api.db.models import PbxSupervisionSessionModel


class PbxSupervisionClient(BaseDBClient):
    async def record_supervision_session(
        self, organization_id: int, fields: dict[str, Any]
    ) -> PbxSupervisionSessionModel:
        async with self.async_session() as session:
            row = PbxSupervisionSessionModel(organization_id=organization_id, **fields)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def list_supervision_sessions(
        self, organization_id: int, limit: int = 50
    ) -> list[PbxSupervisionSessionModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxSupervisionSessionModel)
                .where(PbxSupervisionSessionModel.organization_id == organization_id)
                .order_by(
                    PbxSupervisionSessionModel.created_at.desc(),
                    PbxSupervisionSessionModel.id.desc(),
                )
                .limit(limit)
            )
            return list(result.scalars().all())

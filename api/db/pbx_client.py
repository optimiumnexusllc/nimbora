"""Data access for the organization's enterprise PBX connection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from api.db.base_client import BaseDBClient
from api.db.models import PbxConnectionModel

_UPDATABLE = {
    "name",
    "base_url",
    "username",
    "password",
    "tenant_uuid",
    "verify_tls",
    "ari_configuration_id",
    "incall_context",
    "webhook_token",
    "webhook_subscription_uuid",
    "engine_version",
    "status",
    "last_error",
    "last_checked_at",
    "branding_applied_at",
}


class PbxConnectionClient(BaseDBClient):
    async def get_pbx_connection(
        self, organization_id: int
    ) -> PbxConnectionModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxConnectionModel).where(
                    PbxConnectionModel.organization_id == organization_id
                )
            )
            return result.scalars().first()

    async def get_pbx_connection_by_webhook_token(
        self, token: str
    ) -> PbxConnectionModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxConnectionModel).where(
                    PbxConnectionModel.webhook_token == token
                )
            )
            return result.scalars().first()

    async def list_pbx_connections(self) -> list[PbxConnectionModel]:
        async with self.async_session() as session:
            result = await session.execute(select(PbxConnectionModel))
            return list(result.scalars().all())

    async def save_pbx_connection(
        self, organization_id: int, fields: dict[str, Any]
    ) -> PbxConnectionModel:
        """Create the organization's connection, or update the existing one."""
        values = {k: v for k, v in fields.items() if k in _UPDATABLE}
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxConnectionModel).where(
                    PbxConnectionModel.organization_id == organization_id
                )
            )
            row = result.scalars().first()
            if row is None:
                row = PbxConnectionModel(organization_id=organization_id, **values)
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return row

    async def delete_pbx_connection(self, organization_id: int) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxConnectionModel).where(
                    PbxConnectionModel.organization_id == organization_id
                )
            )
            row = result.scalars().first()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

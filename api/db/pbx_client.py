"""Data access for the organization's enterprise PBX connection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select

from api.db.base_client import BaseDBClient
from api.db.models import PbxCallRecordingModel, PbxConnectionModel, PbxIvrMenuModel

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
    "recording_policy",
    "recordings_synced_at",
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


_MENU_UPDATABLE = {
    "name",
    "spec",
    "pbx_ivr_id",
    "sounds",
    "published_at",
    "published_spec_hash",
    "last_error",
}


class PbxIvrMenuClient(BaseDBClient):
    """Voice menus, always scoped to their organization."""

    async def list_pbx_ivr_menus(self, organization_id: int) -> list[PbxIvrMenuModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxIvrMenuModel)
                .where(PbxIvrMenuModel.organization_id == organization_id)
                .order_by(PbxIvrMenuModel.id)
            )
            return list(result.scalars().all())

    async def get_pbx_ivr_menu(
        self, menu_id: int, organization_id: int
    ) -> PbxIvrMenuModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxIvrMenuModel).where(
                    PbxIvrMenuModel.id == menu_id,
                    PbxIvrMenuModel.organization_id == organization_id,
                )
            )
            return result.scalars().first()

    async def create_pbx_ivr_menu(
        self, organization_id: int, name: str, spec: dict[str, Any]
    ) -> PbxIvrMenuModel:
        async with self.async_session() as session:
            row = PbxIvrMenuModel(
                organization_id=organization_id, name=name, spec=spec, sounds={}
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def update_pbx_ivr_menu(
        self, menu_id: int, organization_id: int, fields: dict[str, Any]
    ) -> PbxIvrMenuModel | None:
        values = {k: v for k, v in fields.items() if k in _MENU_UPDATABLE}
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxIvrMenuModel).where(
                    PbxIvrMenuModel.id == menu_id,
                    PbxIvrMenuModel.organization_id == organization_id,
                )
            )
            row = result.scalars().first()
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return row

    async def delete_pbx_ivr_menu(self, menu_id: int, organization_id: int) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxIvrMenuModel).where(
                    PbxIvrMenuModel.id == menu_id,
                    PbxIvrMenuModel.organization_id == organization_id,
                )
            )
            row = result.scalars().first()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


class PbxCallRecordingClient(BaseDBClient):
    """Human call recordings imported from the PBX, scoped to an organization."""

    async def list_pbx_recordings(
        self,
        organization_id: int,
        *,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[PbxCallRecordingModel], int]:
        async with self.async_session() as session:
            where = [PbxCallRecordingModel.organization_id == organization_id]
            if search:
                like = f"%{search}%"
                where.append(
                    or_(
                        PbxCallRecordingModel.source.ilike(like),
                        PbxCallRecordingModel.destination.ilike(like),
                        PbxCallRecordingModel.source_name.ilike(like),
                        PbxCallRecordingModel.destination_name.ilike(like),
                        PbxCallRecordingModel.transcript.ilike(like),
                    )
                )
            total = (
                await session.execute(
                    select(func.count(PbxCallRecordingModel.id)).where(*where)
                )
            ).scalar() or 0
            result = await session.execute(
                select(PbxCallRecordingModel)
                .where(*where)
                .order_by(PbxCallRecordingModel.started_at.desc().nullslast())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all()), int(total)

    async def get_pbx_recording(
        self, organization_id: int, recording_id: int
    ) -> PbxCallRecordingModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxCallRecordingModel).where(
                    PbxCallRecordingModel.id == recording_id,
                    PbxCallRecordingModel.organization_id == organization_id,
                )
            )
            return result.scalars().first()

    async def known_pbx_recording_uuids(
        self, organization_id: int, uuids: list[str]
    ) -> set[str]:
        if not uuids:
            return set()
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxCallRecordingModel.recording_uuid).where(
                    PbxCallRecordingModel.organization_id == organization_id,
                    PbxCallRecordingModel.recording_uuid.in_(uuids),
                )
            )
            return set(result.scalars().all())

    async def create_pbx_recording(
        self, organization_id: int, fields: dict[str, Any]
    ) -> PbxCallRecordingModel:
        async with self.async_session() as session:
            row = PbxCallRecordingModel(organization_id=organization_id, **fields)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def update_pbx_recording(
        self, organization_id: int, recording_id: int, fields: dict[str, Any]
    ) -> None:
        async with self.async_session() as session:
            row = (
                (
                    await session.execute(
                        select(PbxCallRecordingModel).where(
                            PbxCallRecordingModel.id == recording_id,
                            PbxCallRecordingModel.organization_id == organization_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)
            await session.commit()

    async def delete_pbx_recording(
        self, organization_id: int, recording_id: int
    ) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                delete(PbxCallRecordingModel).where(
                    PbxCallRecordingModel.id == recording_id,
                    PbxCallRecordingModel.organization_id == organization_id,
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def list_pbx_recordings_before(
        self, organization_id: int, before: datetime, limit: int = 200
    ) -> list[PbxCallRecordingModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxCallRecordingModel)
                .where(
                    PbxCallRecordingModel.organization_id == organization_id,
                    PbxCallRecordingModel.started_at < before,
                )
                .limit(limit)
            )
            return list(result.scalars().all())

    async def list_pbx_recordings_for_phone(
        self, organization_id: int, phones: list[str]
    ) -> list[PbxCallRecordingModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(PbxCallRecordingModel).where(
                    PbxCallRecordingModel.organization_id == organization_id,
                    PbxCallRecordingModel.customer_phone.in_(phones),
                )
            )
            return list(result.scalars().all())

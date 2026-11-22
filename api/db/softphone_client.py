"""Data access for NIMBORA Softphone activations and devices."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from api.db.base_client import BaseDBClient
from api.db.models import SoftphoneActivationModel, SoftphoneDeviceModel


class SoftphoneClient(BaseDBClient):
    async def create_softphone_activation(
        self, organization_id: int, fields: dict[str, Any]
    ) -> SoftphoneActivationModel:
        async with self.async_session() as session:
            row = SoftphoneActivationModel(organization_id=organization_id, **fields)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def consume_softphone_activation(
        self, code_hash: str
    ) -> SoftphoneActivationModel | None:
        """Mark a valid, unused, unexpired code as used — exactly once."""
        now = datetime.now(UTC)
        async with self.async_session() as session:
            result = await session.execute(
                update(SoftphoneActivationModel)
                .where(
                    SoftphoneActivationModel.code_hash == code_hash,
                    SoftphoneActivationModel.used_at.is_(None),
                    SoftphoneActivationModel.expires_at > now,
                )
                .values(used_at=now)
                .returning(SoftphoneActivationModel.id)
            )
            activation_id = result.scalar()
            await session.commit()
            if activation_id is None:
                return None
            return await session.get(SoftphoneActivationModel, activation_id)

    async def create_softphone_device(
        self, organization_id: int, fields: dict[str, Any]
    ) -> SoftphoneDeviceModel:
        async with self.async_session() as session:
            # Pairing is the device's first connection.
            row = SoftphoneDeviceModel(
                organization_id=organization_id,
                last_seen_at=datetime.now(UTC),
                **fields,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_softphone_device_by_token(
        self, token_hash: str
    ) -> SoftphoneDeviceModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(SoftphoneDeviceModel).where(
                    SoftphoneDeviceModel.token_hash == token_hash,
                    SoftphoneDeviceModel.revoked_at.is_(None),
                )
            )
            return result.scalars().first()

    async def touch_softphone_device(
        self, organization_id: int, device_id: int, fields: dict[str, Any]
    ) -> None:
        async with self.async_session() as session:
            await session.execute(
                update(SoftphoneDeviceModel)
                .where(
                    SoftphoneDeviceModel.id == device_id,
                    SoftphoneDeviceModel.organization_id == organization_id,
                )
                .values(last_seen_at=datetime.now(UTC), **fields)
            )
            await session.commit()

    async def list_softphone_devices(
        self, organization_id: int, *, include_revoked: bool = False
    ) -> list[SoftphoneDeviceModel]:
        async with self.async_session() as session:
            query = select(SoftphoneDeviceModel).where(
                SoftphoneDeviceModel.organization_id == organization_id
            )
            if not include_revoked:
                query = query.where(SoftphoneDeviceModel.revoked_at.is_(None))
            result = await session.execute(
                query.order_by(SoftphoneDeviceModel.created_at.desc())
            )
            return list(result.scalars().all())

    async def revoke_softphone_device(
        self, organization_id: int, device_id: int
    ) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                update(SoftphoneDeviceModel)
                .where(
                    SoftphoneDeviceModel.id == device_id,
                    SoftphoneDeviceModel.organization_id == organization_id,
                    SoftphoneDeviceModel.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()
            return result.rowcount > 0

    async def revoke_softphone_devices_for_organization(
        self, organization_id: int
    ) -> int:
        """Every device of the company (its PBX is gone)."""
        async with self.async_session() as session:
            result = await session.execute(
                update(SoftphoneDeviceModel)
                .where(
                    SoftphoneDeviceModel.organization_id == organization_id,
                    SoftphoneDeviceModel.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()
            return result.rowcount

    async def revoke_softphone_devices_for_extension(
        self, organization_id: int, pbx_user_uuid: str
    ) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                update(SoftphoneDeviceModel)
                .where(
                    SoftphoneDeviceModel.organization_id == organization_id,
                    SoftphoneDeviceModel.pbx_user_uuid == pbx_user_uuid,
                    SoftphoneDeviceModel.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()
            return result.rowcount

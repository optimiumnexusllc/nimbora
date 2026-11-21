"""Database access for WhatsApp conversations (messaging).

Lookups from the webhook are keyed on the business number and the customer,
always together with the organization resolved from the verified WhatsApp
Business Account. The idle sweep is the only cross-tenant query.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import WhatsAppConversationModel

CONVERSATION_MUTABLE_FIELDS = {
    "customer_name",
    "workflow_id",
    "workflow_run_id",
    "status",
    "message_count",
    "last_inbound_at",
    "last_outbound_at",
    "closed_at",
}


class WhatsAppConversationClient(BaseDBClient):
    async def get_open_whatsapp_conversation(
        self, organization_id: int, phone_number_id: str, customer_wa_id: str
    ) -> WhatsAppConversationModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(WhatsAppConversationModel)
                .where(
                    WhatsAppConversationModel.organization_id == organization_id,
                    WhatsAppConversationModel.phone_number_id == phone_number_id,
                    WhatsAppConversationModel.customer_wa_id == customer_wa_id,
                    WhatsAppConversationModel.status == "open",
                )
                .execution_options(populate_existing=True)
            )
            return result.scalars().first()

    async def open_whatsapp_conversation(
        self, **fields: Any
    ) -> WhatsAppConversationModel:
        """Create the open conversation, or return the one a racing message created."""
        try:
            async with self.async_session() as session:
                row = WhatsAppConversationModel(status="open", **fields)
                session.add(row)
                await session.commit()
        except IntegrityError:
            pass
        existing = await self.get_open_whatsapp_conversation(
            fields["organization_id"],
            fields["phone_number_id"],
            fields["customer_wa_id"],
        )
        assert existing is not None
        return existing

    async def get_whatsapp_conversation(
        self, organization_id: int, conversation_id: int
    ) -> WhatsAppConversationModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(WhatsAppConversationModel)
                .where(
                    WhatsAppConversationModel.organization_id == organization_id,
                    WhatsAppConversationModel.id == conversation_id,
                )
                .execution_options(populate_existing=True)
            )
            return result.scalars().first()

    async def update_whatsapp_conversation(
        self, organization_id: int, conversation_id: int, fields: dict[str, Any]
    ) -> WhatsAppConversationModel | None:
        values = {k: v for k, v in fields.items() if k in CONVERSATION_MUTABLE_FIELDS}
        if values:
            async with self.async_session() as session:
                await session.execute(
                    update(WhatsAppConversationModel)
                    .where(
                        WhatsAppConversationModel.organization_id == organization_id,
                        WhatsAppConversationModel.id == conversation_id,
                    )
                    .values(**values)
                )
                await session.commit()
        return await self.get_whatsapp_conversation(organization_id, conversation_id)

    async def list_whatsapp_conversations(
        self, organization_id: int, *, status: str | None = None, limit: int = 100
    ) -> list[WhatsAppConversationModel]:
        async with self.async_session() as session:
            query = select(WhatsAppConversationModel).where(
                WhatsAppConversationModel.organization_id == organization_id
            )
            if status:
                query = query.where(WhatsAppConversationModel.status == status)
            result = await session.execute(
                query.order_by(
                    WhatsAppConversationModel.last_inbound_at.desc().nullslast()
                ).limit(limit)
            )
            return list(result.scalars().all())

    async def list_idle_whatsapp_conversations(
        self, inactive_since: datetime, limit: int = 200
    ) -> list[WhatsAppConversationModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(WhatsAppConversationModel)
                .where(
                    WhatsAppConversationModel.status == "open",
                    WhatsAppConversationModel.last_inbound_at < inactive_since,
                )
                .order_by(WhatsAppConversationModel.last_inbound_at)
                .limit(limit)
            )
            return list(result.scalars().all())

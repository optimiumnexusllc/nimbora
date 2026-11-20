"""Database access for human contact-center queues and agents.

Every read and write is scoped by ``organization_id`` so one tenant can never
see or change another tenant's queues or agents.
"""

from typing import Any

from sqlalchemy import delete, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    ContactCenterAgentModel,
    ContactCenterQueueModel,
    contact_center_queue_members,
)


class ContactCenterConflict(Exception):
    """A unique queue slug, extension or SIP username is already taken."""


QUEUE_MUTABLE_FIELDS = {
    "name",
    "strategy",
    "ring_timeout_seconds",
    "max_wait_seconds",
    "wrapup_seconds",
    "announce_position",
    "overflow_destination",
    "is_active",
}
AGENT_MUTABLE_FIELDS = {"display_name", "user_id", "is_active", "sip_md5_cred"}


class ContactCenterClient(BaseDBClient):
    # ----------------------------------------------------------------- queues
    async def list_contact_center_queues(
        self, organization_id: int
    ) -> list[ContactCenterQueueModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(ContactCenterQueueModel)
                .where(ContactCenterQueueModel.organization_id == organization_id)
                .order_by(ContactCenterQueueModel.id)
            )
            return list(result.scalars().all())

    async def get_contact_center_queue(
        self, organization_id: int, queue_id: int
    ) -> ContactCenterQueueModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(ContactCenterQueueModel).where(
                    ContactCenterQueueModel.organization_id == organization_id,
                    ContactCenterQueueModel.id == queue_id,
                )
            )
            return result.scalars().first()

    async def get_contact_center_queue_by_slug(
        self, organization_id: int, slug: str
    ) -> ContactCenterQueueModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(ContactCenterQueueModel).where(
                    ContactCenterQueueModel.organization_id == organization_id,
                    ContactCenterQueueModel.slug == slug,
                )
            )
            return result.scalars().first()

    async def create_contact_center_queue(
        self, organization_id: int, slug: str, fields: dict[str, Any]
    ) -> ContactCenterQueueModel:
        values = {k: v for k, v in fields.items() if k in QUEUE_MUTABLE_FIELDS}
        async with self.async_session() as session:
            taken = await session.execute(
                select(ContactCenterQueueModel.id).where(
                    ContactCenterQueueModel.organization_id == organization_id,
                    ContactCenterQueueModel.slug == slug,
                )
            )
            if taken.first() is not None:
                raise ContactCenterConflict("queue slug already exists")
            queue = ContactCenterQueueModel(
                organization_id=organization_id, slug=slug, **values
            )
            session.add(queue)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ContactCenterConflict("queue slug already exists") from exc
            queue_id = queue.id
            await session.commit()
        created = await self.get_contact_center_queue(organization_id, queue_id)
        assert created is not None
        return created

    async def update_contact_center_queue(
        self, organization_id: int, queue_id: int, fields: dict[str, Any]
    ) -> ContactCenterQueueModel | None:
        values = {k: v for k, v in fields.items() if k in QUEUE_MUTABLE_FIELDS}
        if values:
            async with self.async_session() as session:
                await session.execute(
                    update(ContactCenterQueueModel)
                    .where(
                        ContactCenterQueueModel.organization_id == organization_id,
                        ContactCenterQueueModel.id == queue_id,
                    )
                    .values(**values)
                )
                await session.commit()
        return await self.get_contact_center_queue(organization_id, queue_id)

    async def delete_contact_center_queue(
        self, organization_id: int, queue_id: int
    ) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                delete(ContactCenterQueueModel).where(
                    ContactCenterQueueModel.organization_id == organization_id,
                    ContactCenterQueueModel.id == queue_id,
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def set_contact_center_queue_members(
        self, organization_id: int, queue_id: int, agent_ids: list[int]
    ) -> ContactCenterQueueModel | None:
        """Replace a queue's members. Agents of other tenants are rejected."""
        async with self.async_session() as session:
            owned_queue = await session.execute(
                select(ContactCenterQueueModel.id).where(
                    ContactCenterQueueModel.organization_id == organization_id,
                    ContactCenterQueueModel.id == queue_id,
                )
            )
            if owned_queue.scalar() is None:
                return None
            unique_ids = sorted(set(agent_ids))
            if unique_ids:
                owned = await session.execute(
                    select(ContactCenterAgentModel.id).where(
                        ContactCenterAgentModel.organization_id == organization_id,
                        ContactCenterAgentModel.id.in_(unique_ids),
                    )
                )
                owned_ids = {row[0] for row in owned.all()}
                if owned_ids != set(unique_ids):
                    raise ValueError("Unknown agent for this organization")
            await session.execute(
                delete(contact_center_queue_members).where(
                    contact_center_queue_members.c.queue_id == queue_id
                )
            )
            if unique_ids:
                await session.execute(
                    insert(contact_center_queue_members),
                    [
                        {"queue_id": queue_id, "agent_id": agent_id, "penalty": 0}
                        for agent_id in unique_ids
                    ],
                )
            await session.commit()
        return await self.get_contact_center_queue(organization_id, queue_id)

    # ----------------------------------------------------------------- agents
    async def list_contact_center_agents(
        self, organization_id: int
    ) -> list[ContactCenterAgentModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(ContactCenterAgentModel)
                .where(ContactCenterAgentModel.organization_id == organization_id)
                .order_by(ContactCenterAgentModel.extension)
            )
            return list(result.scalars().all())

    async def get_contact_center_agent(
        self, organization_id: int, agent_id: int
    ) -> ContactCenterAgentModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(ContactCenterAgentModel).where(
                    ContactCenterAgentModel.organization_id == organization_id,
                    ContactCenterAgentModel.id == agent_id,
                )
            )
            return result.scalars().first()

    async def get_contact_center_agent_for_user(
        self, organization_id: int, user_id: int
    ) -> ContactCenterAgentModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(ContactCenterAgentModel).where(
                    ContactCenterAgentModel.organization_id == organization_id,
                    ContactCenterAgentModel.user_id == user_id,
                )
            )
            return result.scalars().first()

    async def count_contact_center_agents(self, organization_id: int) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                select(func.count(ContactCenterAgentModel.id)).where(
                    ContactCenterAgentModel.organization_id == organization_id,
                    ContactCenterAgentModel.is_active.is_(True),
                )
            )
            return int(result.scalar_one())

    async def create_contact_center_agent(
        self,
        organization_id: int,
        *,
        display_name: str,
        extension: str,
        sip_username: str,
        sip_md5_cred: str,
        user_id: int | None = None,
    ) -> ContactCenterAgentModel:
        async with self.async_session() as session:
            taken = await session.execute(
                select(ContactCenterAgentModel.id).where(
                    (ContactCenterAgentModel.sip_username == sip_username)
                    | (
                        (ContactCenterAgentModel.organization_id == organization_id)
                        & (ContactCenterAgentModel.extension == extension)
                    )
                )
            )
            if taken.first() is not None:
                raise ContactCenterConflict("extension already in use")
            agent = ContactCenterAgentModel(
                organization_id=organization_id,
                display_name=display_name,
                extension=extension,
                sip_username=sip_username,
                sip_md5_cred=sip_md5_cred,
                user_id=user_id,
                is_active=True,
            )
            session.add(agent)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ContactCenterConflict("extension already in use") from exc
            agent_id = agent.id
            await session.commit()
        created = await self.get_contact_center_agent(organization_id, agent_id)
        assert created is not None
        return created

    async def update_contact_center_agent(
        self, organization_id: int, agent_id: int, fields: dict[str, Any]
    ) -> ContactCenterAgentModel | None:
        values = {k: v for k, v in fields.items() if k in AGENT_MUTABLE_FIELDS}
        if values:
            async with self.async_session() as session:
                await session.execute(
                    update(ContactCenterAgentModel)
                    .where(
                        ContactCenterAgentModel.organization_id == organization_id,
                        ContactCenterAgentModel.id == agent_id,
                    )
                    .values(**values)
                )
                await session.commit()
        return await self.get_contact_center_agent(organization_id, agent_id)

    async def delete_contact_center_agent(
        self, organization_id: int, agent_id: int
    ) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                delete(ContactCenterAgentModel).where(
                    ContactCenterAgentModel.organization_id == organization_id,
                    ContactCenterAgentModel.id == agent_id,
                )
            )
            await session.commit()
            return result.rowcount > 0

    # ------------------------------------------------- whole-platform export
    async def list_all_active_contact_center_config(
        self,
    ) -> tuple[list[ContactCenterQueueModel], list[ContactCenterAgentModel]]:
        """Every tenant's active queues and agents, to render Asterisk config."""
        async with self.async_session() as session:
            queues = await session.execute(
                select(ContactCenterQueueModel)
                .where(ContactCenterQueueModel.is_active.is_(True))
                .order_by(
                    ContactCenterQueueModel.organization_id, ContactCenterQueueModel.id
                )
            )
            agents = await session.execute(
                select(ContactCenterAgentModel)
                .where(ContactCenterAgentModel.is_active.is_(True))
                .order_by(
                    ContactCenterAgentModel.organization_id,
                    ContactCenterAgentModel.extension,
                )
            )
            return list(queues.scalars().all()), list(agents.scalars().all())

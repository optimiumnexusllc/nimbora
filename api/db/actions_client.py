"""Database access for agent actions: appointments, messages, tickets.

All reads and writes are filtered by ``organization_id``.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import AppointmentModel, SentMessageModel, TicketModel

TICKET_MUTABLE_FIELDS = {
    "status",
    "priority",
    "category",
    "resolution",
    "assigned_user_id",
    "subject",
    "description",
    "external_id",
    "external_url",
}


class ActionsClient(BaseDBClient):
    # -------------------------------------------------------- appointments
    async def create_appointment(self, **fields: Any) -> AppointmentModel:
        async with self.async_session() as session:
            row = AppointmentModel(**fields)
            session.add(row)
            await session.flush()
            row_id = row.id
            await session.commit()
        return await self.get_appointment(fields["organization_id"], row_id)

    async def get_appointment(
        self, organization_id: int, appointment_id: int
    ) -> AppointmentModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(AppointmentModel)
                .where(
                    AppointmentModel.organization_id == organization_id,
                    AppointmentModel.id == appointment_id,
                )
                .execution_options(populate_existing=True)
            )
            return result.scalars().first()

    async def list_booked_appointments_between(
        self,
        organization_id: int,
        calendar_key: str,
        start: datetime,
        end: datetime,
    ) -> list[AppointmentModel]:
        """Booked appointments of one calendar overlapping [start, end)."""
        async with self.async_session() as session:
            result = await session.execute(
                select(AppointmentModel)
                .where(
                    AppointmentModel.organization_id == organization_id,
                    AppointmentModel.calendar_key == calendar_key,
                    AppointmentModel.status == "booked",
                    AppointmentModel.start_at < end,
                    AppointmentModel.end_at > start,
                )
                .order_by(AppointmentModel.start_at)
            )
            return list(result.scalars().all())

    async def list_appointments(
        self,
        organization_id: int,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        phone: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[AppointmentModel]:
        async with self.async_session() as session:
            query = select(AppointmentModel).where(
                AppointmentModel.organization_id == organization_id
            )
            if start is not None:
                query = query.where(AppointmentModel.end_at > start)
            if end is not None:
                query = query.where(AppointmentModel.start_at < end)
            if phone:
                query = query.where(AppointmentModel.phone == phone)
            if status:
                query = query.where(AppointmentModel.status == status)
            result = await session.execute(
                query.order_by(AppointmentModel.start_at).limit(limit)
            )
            return list(result.scalars().all())

    async def cancel_appointment(
        self, organization_id: int, appointment_id: int
    ) -> AppointmentModel | None:
        async with self.async_session() as session:
            await session.execute(
                update(AppointmentModel)
                .where(
                    AppointmentModel.organization_id == organization_id,
                    AppointmentModel.id == appointment_id,
                    AppointmentModel.status == "booked",
                )
                .values(status="canceled", canceled_at=datetime.now(UTC))
            )
            await session.commit()
        return await self.get_appointment(organization_id, appointment_id)

    # ------------------------------------------------------------ messages
    async def create_sent_message(self, **fields: Any) -> SentMessageModel:
        async with self.async_session() as session:
            row = SentMessageModel(**fields)
            session.add(row)
            await session.flush()
            row_id = row.id
            await session.commit()
        async with self.async_session() as session:
            result = await session.execute(
                select(SentMessageModel).where(SentMessageModel.id == row_id)
            )
            return result.scalars().one()

    async def count_messages_for_run(
        self, organization_id: int, workflow_run_id: int, tool_uuid: str
    ) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                select(func.count(SentMessageModel.id)).where(
                    SentMessageModel.organization_id == organization_id,
                    SentMessageModel.workflow_run_id == workflow_run_id,
                    SentMessageModel.tool_uuid == tool_uuid,
                    SentMessageModel.status == "sent",
                )
            )
            return int(result.scalar_one())

    async def list_sent_messages(
        self, organization_id: int, *, limit: int = 200
    ) -> list[SentMessageModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(SentMessageModel)
                .where(SentMessageModel.organization_id == organization_id)
                .order_by(SentMessageModel.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    # ------------------------------------------------------------- tickets
    async def create_ticket(self, **fields: Any) -> TicketModel:
        """Insert with the next per-organization number (retry on a race)."""
        organization_id = fields["organization_id"]
        for _ in range(5):
            try:
                async with self.async_session() as session:
                    result = await session.execute(
                        select(func.coalesce(func.max(TicketModel.number), 1000)).where(
                            TicketModel.organization_id == organization_id
                        )
                    )
                    number = int(result.scalar_one()) + 1
                    row = TicketModel(**fields, number=number)
                    session.add(row)
                    await session.flush()
                    row_id = row.id
                    await session.commit()
                return await self.get_ticket(organization_id, row_id)
            except IntegrityError:
                continue
        raise RuntimeError("Could not allocate a ticket number")

    async def get_ticket(
        self, organization_id: int, ticket_id: int
    ) -> TicketModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(TicketModel)
                .where(
                    TicketModel.organization_id == organization_id,
                    TicketModel.id == ticket_id,
                )
                .execution_options(populate_existing=True)
            )
            return result.scalars().first()

    async def get_ticket_by_number(
        self, organization_id: int, number: int
    ) -> TicketModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(TicketModel).where(
                    TicketModel.organization_id == organization_id,
                    TicketModel.number == number,
                )
            )
            return result.scalars().first()

    async def list_tickets(
        self,
        organization_id: int,
        *,
        statuses: list[str] | None = None,
        phone: str | None = None,
        limit: int = 200,
    ) -> list[TicketModel]:
        async with self.async_session() as session:
            query = select(TicketModel).where(
                TicketModel.organization_id == organization_id
            )
            if statuses:
                query = query.where(TicketModel.status.in_(statuses))
            if phone:
                query = query.where(TicketModel.phone == phone)
            result = await session.execute(
                query.order_by(TicketModel.created_at.desc()).limit(limit)
            )
            return list(result.scalars().all())

    async def update_ticket(
        self, organization_id: int, ticket_id: int, fields: dict[str, Any]
    ) -> TicketModel | None:
        values = {k: v for k, v in fields.items() if k in TICKET_MUTABLE_FIELDS}
        if values:
            values["updated_at"] = datetime.now(UTC)
            async with self.async_session() as session:
                await session.execute(
                    update(TicketModel)
                    .where(
                        TicketModel.organization_id == organization_id,
                        TicketModel.id == ticket_id,
                    )
                    .values(**values)
                )
                await session.commit()
        return await self.get_ticket(organization_id, ticket_id)

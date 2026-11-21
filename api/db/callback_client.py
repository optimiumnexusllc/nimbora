"""Database access for callback requests.

Tenant-facing reads and writes are filtered by ``organization_id``. The only
cross-tenant queries are the scheduler's (due AI callbacks, abandoned
handoffs), which run in a background job, never from a request.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, update
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    CallbackRequestModel,
    CallHandoffModel,
    ContactCenterQueueModel,
)

OPEN_STATUSES = ("pending", "in_progress")
CALLBACK_MUTABLE_FIELDS = {
    "customer_name",
    "reason",
    "assign_to",
    "queue_slug",
    "workflow_id",
    "status",
    "scheduled_at",
    "attempts",
    "max_attempts",
    "last_attempt_at",
    "callback_workflow_run_id",
    "assigned_agent_id",
    "outcome",
    "notes",
    "completed_at",
}


class CallbackClient(BaseDBClient):
    async def create_callback_request(self, **fields: Any) -> CallbackRequestModel:
        async with self.async_session() as session:
            callback = CallbackRequestModel(**fields)
            session.add(callback)
            await session.flush()
            callback_id = callback.id
            await session.commit()
        created = await self.get_callback_request(
            fields["organization_id"], callback_id
        )
        assert created is not None
        return created

    async def get_callback_request(
        self, organization_id: int, callback_id: int
    ) -> CallbackRequestModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackRequestModel)
                .where(
                    CallbackRequestModel.organization_id == organization_id,
                    CallbackRequestModel.id == callback_id,
                )
                .execution_options(populate_existing=True)
            )
            return result.scalars().first()

    async def find_open_callback_for_phone(
        self, organization_id: int, phone: str
    ) -> CallbackRequestModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackRequestModel)
                .where(
                    CallbackRequestModel.organization_id == organization_id,
                    CallbackRequestModel.phone == phone,
                    CallbackRequestModel.status.in_(OPEN_STATUSES),
                )
                .order_by(CallbackRequestModel.created_at.desc())
                .limit(1)
            )
            return result.scalars().first()

    async def update_callback_request(
        self, organization_id: int, callback_id: int, fields: dict[str, Any]
    ) -> CallbackRequestModel | None:
        values = {k: v for k, v in fields.items() if k in CALLBACK_MUTABLE_FIELDS}
        if values:
            async with self.async_session() as session:
                await session.execute(
                    update(CallbackRequestModel)
                    .where(
                        CallbackRequestModel.organization_id == organization_id,
                        CallbackRequestModel.id == callback_id,
                    )
                    .values(**values)
                )
                await session.commit()
        return await self.get_callback_request(organization_id, callback_id)

    async def claim_callback_request(
        self,
        organization_id: int,
        callback_id: int,
        *,
        from_status: str = "pending",
        fields: dict[str, Any] | None = None,
    ) -> CallbackRequestModel | None:
        """Atomically move a callback out of ``from_status``.

        Returns None when another worker (or agent) claimed it first.
        """
        values = {
            k: v for k, v in (fields or {}).items() if k in CALLBACK_MUTABLE_FIELDS
        }
        values.setdefault("status", "in_progress")
        async with self.async_session() as session:
            result = await session.execute(
                update(CallbackRequestModel)
                .where(
                    CallbackRequestModel.organization_id == organization_id,
                    CallbackRequestModel.id == callback_id,
                    CallbackRequestModel.status == from_status,
                )
                .values(**values)
                .returning(CallbackRequestModel.id)
            )
            claimed = result.first() is not None
            await session.commit()
        if not claimed:
            return None
        return await self.get_callback_request(organization_id, callback_id)

    async def list_callback_requests(
        self,
        organization_id: int,
        *,
        statuses: list[str] | None = None,
        limit: int = 100,
    ) -> list[CallbackRequestModel]:
        async with self.async_session() as session:
            query = select(CallbackRequestModel).where(
                CallbackRequestModel.organization_id == organization_id
            )
            if statuses:
                query = query.where(CallbackRequestModel.status.in_(statuses))
            query = query.order_by(
                CallbackRequestModel.status.in_(OPEN_STATUSES).desc(),
                CallbackRequestModel.scheduled_at.asc(),
            ).limit(limit)
            result = await session.execute(query)
            return list(result.scalars().all())

    async def list_callbacks_by_source(
        self, organization_id: int, source: str, limit: int = 20
    ) -> list[CallbackRequestModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackRequestModel)
                .where(
                    CallbackRequestModel.organization_id == organization_id,
                    CallbackRequestModel.source == source,
                )
                .order_by(CallbackRequestModel.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def count_open_callback_requests(self, organization_id: int) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                select(func.count(CallbackRequestModel.id)).where(
                    CallbackRequestModel.organization_id == organization_id,
                    CallbackRequestModel.status == "pending",
                )
            )
            return int(result.scalar_one())

    async def get_callback_for_run(
        self, organization_id: int, workflow_run_id: int
    ) -> CallbackRequestModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackRequestModel).where(
                    CallbackRequestModel.organization_id == organization_id,
                    CallbackRequestModel.callback_workflow_run_id == workflow_run_id,
                )
            )
            return result.scalars().first()

    # ------------------------------------------------------------- scheduler
    async def list_due_ai_callbacks(
        self, now: datetime, limit: int = 50
    ) -> list[CallbackRequestModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackRequestModel)
                .where(
                    CallbackRequestModel.status == "pending",
                    CallbackRequestModel.assign_to == "ai",
                    CallbackRequestModel.scheduled_at <= now,
                )
                .order_by(CallbackRequestModel.scheduled_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def list_stale_pending_handoffs(
        self, now: datetime, default_wait_seconds: int = 300, limit: int = 200
    ) -> list[tuple[CallHandoffModel, int]]:
        """Pending handoffs older than their queue's max wait (+2 min).

        Returns (handoff, queue max wait) pairs.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    CallHandoffModel,
                    func.coalesce(
                        ContactCenterQueueModel.max_wait_seconds, default_wait_seconds
                    ),
                )
                .outerjoin(
                    ContactCenterQueueModel,
                    (
                        ContactCenterQueueModel.organization_id
                        == CallHandoffModel.organization_id
                    )
                    & (ContactCenterQueueModel.slug == CallHandoffModel.queue_slug),
                )
                .where(CallHandoffModel.status == "pending")
                # Enterprise PBX cards are closed from the PBX's call logs.
                .where(
                    or_(
                        CallHandoffModel.queue_slug.is_(None),
                        ~CallHandoffModel.queue_slug.startswith("pbx:"),
                    )
                )
                .order_by(CallHandoffModel.created_at.asc())
                .limit(limit)
            )
            stale = []
            for handoff, max_wait in result.all():
                created = handoff.created_at
                if created is None:
                    continue
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                if (now - created).total_seconds() > int(max_wait) + 120:
                    stale.append((handoff, int(max_wait)))
            return stale

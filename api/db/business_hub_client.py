"""Numbers for the AI Business Hub: what the agents and the team did.

One query per source, all filtered by organization and by the period
[start, end). Daily series are bucketed in the company's time zone.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Float, and_, case, cast, func
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    AppointmentModel,
    CallbackRequestModel,
    CallHandoffModel,
    CustomerProfileModel,
    HumanCallUsageModel,
    LeadModel,
    SentMessageModel,
    TicketModel,
    WhatsAppConversationModel,
    WorkflowModel,
    WorkflowRunModel,
)


def _day(column, tz: str):
    return func.to_char(func.timezone(tz, column), "YYYY-MM-DD")


class BusinessHubClient(BaseDBClient):
    async def hub_ai_runs(
        self, organization_id: int, start: datetime, end: datetime, tz: str
    ) -> list[dict[str, Any]]:
        """AI conversations per day, mode and direction, with their seconds."""
        seconds = func.coalesce(
            cast(
                WorkflowRunModel.usage_info["call_duration_seconds"].as_string(), Float
            ),
            0.0,
        )
        async with self.async_session() as session:
            rows = await session.execute(
                select(
                    _day(WorkflowRunModel.created_at, tz).label("day"),
                    WorkflowRunModel.mode,
                    WorkflowRunModel.call_type,
                    func.count(),
                    func.coalesce(func.sum(seconds), 0.0),
                )
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowRunModel.created_at >= start,
                    WorkflowRunModel.created_at < end,
                )
                .group_by("day", WorkflowRunModel.mode, WorkflowRunModel.call_type)
            )
            return [
                {
                    "day": d,
                    "mode": m,
                    "direction": c,
                    "count": int(n),
                    "seconds": float(s),
                }
                for d, m, c, n, s in rows
            ]

    async def hub_human_calls(
        self, organization_id: int, start: datetime, end: datetime, tz: str
    ) -> list[dict[str, Any]]:
        async with self.async_session() as session:
            rows = await session.execute(
                select(
                    _day(HumanCallUsageModel.started_at, tz).label("day"),
                    HumanCallUsageModel.direction,
                    func.count(),
                    func.coalesce(func.sum(HumanCallUsageModel.billable_seconds), 0),
                )
                .where(
                    HumanCallUsageModel.organization_id == organization_id,
                    HumanCallUsageModel.started_at >= start,
                    HumanCallUsageModel.started_at < end,
                )
                .group_by("day", HumanCallUsageModel.direction)
            )
            return [
                {"day": d, "direction": c, "count": int(n), "seconds": int(s)}
                for d, c, n, s in rows
            ]

    async def hub_counts(
        self, organization_id: int, start: datetime, end: datetime, now: datetime
    ) -> dict[str, int]:
        """Everything else, as plain counts over the period."""

        def window(column):
            return and_(column >= start, column < end)

        queries = {
            "whatsapp_conversations": select(func.count()).where(
                WhatsAppConversationModel.organization_id == organization_id,
                window(WhatsAppConversationModel.created_at),
            ),
            "whatsapp_messages": select(
                func.coalesce(func.sum(WhatsAppConversationModel.message_count), 0)
            ).where(
                WhatsAppConversationModel.organization_id == organization_id,
                window(WhatsAppConversationModel.created_at),
            ),
            "handoffs": select(func.count()).where(
                CallHandoffModel.organization_id == organization_id,
                window(CallHandoffModel.created_at),
            ),
            "handoffs_answered": select(func.count()).where(
                CallHandoffModel.organization_id == organization_id,
                window(CallHandoffModel.created_at),
                CallHandoffModel.answered_at.is_not(None),
            ),
            "appointments_booked": select(func.count()).where(
                AppointmentModel.organization_id == organization_id,
                window(AppointmentModel.created_at),
            ),
            "appointments_canceled": select(func.count()).where(
                AppointmentModel.organization_id == organization_id,
                window(AppointmentModel.created_at),
                AppointmentModel.status == "canceled",
            ),
            "appointments_upcoming": select(func.count()).where(
                AppointmentModel.organization_id == organization_id,
                AppointmentModel.start_at >= now,
                AppointmentModel.status == "booked",
            ),
            "messages_sent": select(func.count()).where(
                SentMessageModel.organization_id == organization_id,
                window(SentMessageModel.created_at),
            ),
            "tickets_created": select(func.count()).where(
                TicketModel.organization_id == organization_id,
                window(TicketModel.created_at),
            ),
            "tickets_open": select(func.count()).where(
                TicketModel.organization_id == organization_id,
                TicketModel.status.not_in(("solved", "closed")),
            ),
            "callbacks_created": select(func.count()).where(
                CallbackRequestModel.organization_id == organization_id,
                window(CallbackRequestModel.created_at),
            ),
            "callbacks_done": select(func.count()).where(
                CallbackRequestModel.organization_id == organization_id,
                window(CallbackRequestModel.created_at),
                CallbackRequestModel.status == "done",
            ),
            "customers_new": select(func.count()).where(
                CustomerProfileModel.organization_id == organization_id,
                window(CustomerProfileModel.first_seen_at),
            ),
            "leads_new": select(func.count()).where(
                LeadModel.organization_id == organization_id,
                window(LeadModel.created_at),
            ),
            "leads_qualified": select(func.count()).where(
                LeadModel.organization_id == organization_id,
                window(LeadModel.created_at),
                LeadModel.stage.not_in(("new", "lost")),
            ),
            "leads_won": select(func.count()).where(
                LeadModel.organization_id == organization_id,
                LeadModel.stage == "won",
                window(LeadModel.closed_at),
            ),
            "leads_lost": select(func.count()).where(
                LeadModel.organization_id == organization_id,
                LeadModel.stage == "lost",
                window(LeadModel.closed_at),
            ),
        }
        result: dict[str, int] = {}
        async with self.async_session() as session:
            for key, query in queries.items():
                result[key] = int((await session.execute(query)).scalar() or 0)
        return result

    async def hub_daily_events(
        self, organization_id: int, start: datetime, end: datetime, tz: str
    ) -> list[dict[str, Any]]:
        """Per day: WhatsApp conversations, appointments, leads."""
        sources = (
            ("whatsapp", WhatsAppConversationModel),
            ("appointments", AppointmentModel),
            ("leads", LeadModel),
        )
        out: list[dict[str, Any]] = []
        async with self.async_session() as session:
            for name, model in sources:
                rows = await session.execute(
                    select(_day(model.created_at, tz).label("day"), func.count())
                    .where(
                        model.organization_id == organization_id,
                        model.created_at >= start,
                        model.created_at < end,
                    )
                    .group_by("day")
                )
                out += [{"day": d, "source": name, "count": int(n)} for d, n in rows]
        return out

    async def hub_open_pipeline(self, organization_id: int) -> list[dict[str, Any]]:
        """Open leads' maximum budgets, per currency."""
        open_stage = case((LeadModel.stage.in_(("won", "lost")), 0), else_=1)
        async with self.async_session() as session:
            rows = await session.execute(
                select(
                    LeadModel.currency,
                    func.sum(open_stage),
                    func.coalesce(
                        func.sum(
                            case((open_stage == 1, LeadModel.budget_max), else_=0)
                        ),
                        0,
                    ),
                )
                .where(LeadModel.organization_id == organization_id)
                .group_by(LeadModel.currency)
            )
            return [
                {"currency": c, "open": int(n or 0), "budget": int(b or 0)}
                for c, n, b in rows
            ]

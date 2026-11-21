"""Agent activity: appointments booked, messages sent, tickets opened."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user

router = APIRouter(prefix="/actions", tags=["actions"])


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_organization_id


class AppointmentResponse(BaseModel):
    id: int
    calendar_key: str
    calendar_name: str | None
    provider: str
    start_at: datetime
    end_at: datetime
    customer_name: str | None
    phone: str | None
    email: str | None
    reason: str | None
    status: str
    workflow_run_id: int | None
    created_at: datetime | None


@router.get("/appointments", response_model=list[AppointmentResponse])
async def list_appointments(
    view: Literal["upcoming", "past", "all"] = "upcoming",
    user: UserModel = Depends(get_user),
):
    organization_id = _org(user)
    now = datetime.now(UTC)
    if view == "upcoming":
        rows = await db_client.list_appointments(organization_id, start=now)
    elif view == "past":
        rows = await db_client.list_appointments(
            organization_id, start=now - timedelta(days=90), end=now
        )
        rows = list(reversed(rows))
    else:
        rows = await db_client.list_appointments(organization_id, limit=500)
    return [AppointmentResponse.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/appointments/{appointment_id}/cancel", response_model=AppointmentResponse
)
async def cancel_appointment(appointment_id: int, user: UserModel = Depends(get_user)):
    """Cancel from the dashboard (also removes it from CalDAV/Google)."""
    organization_id = _org(user)
    appointment = await db_client.get_appointment(organization_id, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appointment.external_id:
        tool = await db_client.get_tool_by_uuid(
            appointment.calendar_key, organization_id
        )
        if tool is not None:
            from api.services.actions.calendar.providers import CalendarError
            from api.services.actions.calendar.service import build_backend
            from api.services.actions.common import ActionContext, ActionError

            ctx = ActionContext(
                organization_id=organization_id,
                tool_uuid=tool.tool_uuid,
                tool_name=tool.name,
            )
            try:
                backend = await build_backend(
                    ctx, (tool.definition or {}).get("config") or {}
                )
                await backend.delete(appointment.external_id)
            except (ActionError, CalendarError) as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
    appointment = await db_client.cancel_appointment(organization_id, appointment_id)
    return AppointmentResponse.model_validate(appointment, from_attributes=True)


class SlotPreviewResponse(BaseModel):
    status: str
    slots: list[dict[str, str]] = []
    timezone: str | None = None
    error: str | None = None


@router.post("/calendars/{tool_uuid}/preview", response_model=SlotPreviewResponse)
async def preview_slots(tool_uuid: str, user: UserModel = Depends(get_user)):
    """Test a calendar tool: connect and list the next free slots."""
    organization_id = _org(user)
    tool = await db_client.get_tool_by_uuid(tool_uuid, organization_id)
    if tool is None or tool.category != "book_appointment":
        raise HTTPException(status_code=404, detail="Calendar tool not found")
    from api.services.actions.common import ActionContext
    from api.services.actions.dispatch import run_action

    result = await run_action(
        "book_appointment",
        ActionContext(
            organization_id=organization_id,
            tool_uuid=tool.tool_uuid,
            tool_name=tool.name,
        ),
        (tool.definition or {}).get("config") or {},
        {"action": "find_slots"},
    )
    return SlotPreviewResponse(
        status=result.get("status", "error"),
        slots=result.get("slots") or [],
        timezone=result.get("timezone"),
        error=result.get("error") or result.get("message"),
    )


class SentMessageResponse(BaseModel):
    id: int
    channel: str
    provider: str
    recipient: str
    subject: str | None
    body: str
    status: str
    error: str | None
    workflow_run_id: int | None
    created_at: datetime | None


@router.get("/messages", response_model=list[SentMessageResponse])
async def list_messages(user: UserModel = Depends(get_user)):
    rows = await db_client.list_sent_messages(_org(user))
    return [SentMessageResponse.model_validate(r, from_attributes=True) for r in rows]


class TicketResponse(BaseModel):
    id: int
    number: int
    provider: str
    external_url: str | None
    subject: str
    description: str | None
    category: str | None
    priority: str
    status: str
    customer_name: str | None
    phone: str | None
    email: str | None
    resolution: str | None
    assigned_user_id: int | None
    workflow_run_id: int | None
    created_at: datetime | None
    updated_at: datetime | None


@router.get("/tickets", response_model=list[TicketResponse])
async def list_tickets(
    view: Literal["open", "closed", "all"] = "open", user: UserModel = Depends(get_user)
):
    statuses = {
        "open": ["open", "pending"],
        "closed": ["solved", "closed"],
        "all": None,
    }[view]
    rows = await db_client.list_tickets(_org(user), statuses=statuses)
    return [TicketResponse.model_validate(r, from_attributes=True) for r in rows]


class TicketUpdateRequest(BaseModel):
    status: Literal["open", "pending", "solved", "closed"] | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    resolution: str | None = Field(default=None, max_length=4000)
    assigned_user_id: int | None = None


@router.patch("/tickets/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: int, request: TicketUpdateRequest, user: UserModel = Depends(get_user)
):
    organization_id = _org(user)
    fields: dict[str, Any] = request.model_dump(exclude_unset=True)
    if fields.get("assigned_user_id") is not None:
        members = await db_client.get_organization_users(organization_id)
        if fields["assigned_user_id"] not in {m.id for m in members}:
            raise HTTPException(status_code=404, detail="User not found")
    ticket = await db_client.update_ticket(organization_id, ticket_id, fields)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return TicketResponse.model_validate(ticket, from_attributes=True)


class ActivitySummary(BaseModel):
    upcoming_appointments: int
    messages_today: int
    open_tickets: int


@router.get("/summary", response_model=ActivitySummary)
async def summary(user: UserModel = Depends(get_user)):
    organization_id = _org(user)
    now = datetime.now(UTC)
    upcoming = await db_client.list_appointments(
        organization_id, start=now, status="booked"
    )
    messages = await db_client.list_sent_messages(organization_id, limit=500)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tickets = await db_client.list_tickets(
        organization_id, statuses=["open", "pending"]
    )
    return ActivitySummary(
        upcoming_appointments=len(upcoming),
        messages_today=sum(
            1 for m in messages if m.created_at and m.created_at >= day_start
        ),
        open_tickets=len(tickets),
    )

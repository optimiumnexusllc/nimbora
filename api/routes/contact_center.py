"""Human contact center: queues, agent seats and softphone credentials.

All routes are scoped to the caller's selected organization. Any change
regenerates the shared Asterisk configuration in the background-safe,
serialized way implemented by ``regenerate_asterisk_config``.
"""

from datetime import UTC, datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.constants import ASTERISK_SIP_REALM, ASTERISK_WSS_URL, CONTACT_CENTER_ENABLED
from api.db import db_client
from api.db.contact_center_client import ContactCenterConflict
from api.db.models import (
    CallHandoffModel,
    ContactCenterAgentModel,
    ContactCenterQueueModel,
    UserModel,
)
from api.services.auth.depends import get_user
from api.services.contact_center.asterisk_config import (
    ALLOWED_STRATEGIES,
    EXTENSION_RE,
    OVERFLOW_NUMBER_RE,
    new_agent_credentials,
    regenerate_asterisk_config,
    sanitize_display_name,
)
from api.services.contact_center.destinations import SLUG_RE
from api.services.saas.limits import enforce_human_seat_limit
from api.services.saas.plans import FEATURE_CONTACT_CENTER
from api.services.saas.subscription_service import check_feature


async def require_contact_center() -> None:
    if not CONTACT_CENTER_ENABLED:
        raise HTTPException(status_code=404, detail="Contact center is not enabled")


router = APIRouter(
    prefix="/contact-center",
    tags=["contact-center"],
    dependencies=[Depends(require_contact_center)],
)


def _validate_overflow(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    value = value.strip()
    if not (EXTENSION_RE.match(value) or OVERFLOW_NUMBER_RE.match(value)):
        raise ValueError("overflow_destination: an agent extension or a number")
    return value


Strategy = Literal[tuple(sorted(ALLOWED_STRATEGIES))]  # type: ignore[valid-type]


class QueueCreateRequest(BaseModel):
    slug: str = Field(description="Short identifier used in transfers: queue:<slug>")
    name: str = Field(min_length=1, max_length=128)
    strategy: Strategy = "rrmemory"
    ring_timeout_seconds: int = Field(20, ge=5, le=120)
    max_wait_seconds: int = Field(300, ge=10, le=3600)
    wrapup_seconds: int = Field(10, ge=0, le=600)
    announce_position: bool = True
    overflow_destination: str | None = None
    agent_ids: list[int] = []

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not SLUG_RE.match(value):
            raise ValueError(
                "slug: lowercase letters, digits, - or _, up to 47 characters"
            )
        return value

    @field_validator("overflow_destination")
    @classmethod
    def _overflow(cls, value: str | None) -> str | None:
        return _validate_overflow(value)


class QueueUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    strategy: Strategy | None = None
    ring_timeout_seconds: int | None = Field(default=None, ge=5, le=120)
    max_wait_seconds: int | None = Field(default=None, ge=10, le=3600)
    wrapup_seconds: int | None = Field(default=None, ge=0, le=600)
    announce_position: bool | None = None
    overflow_destination: str | None = None
    is_active: bool | None = None
    agent_ids: list[int] | None = None

    @field_validator("overflow_destination")
    @classmethod
    def _overflow(cls, value: str | None) -> str | None:
        return _validate_overflow(value)


class AgentSummary(BaseModel):
    id: int
    display_name: str
    extension: str


class QueueResponse(BaseModel):
    id: int
    slug: str
    name: str
    transfer_destination: str
    strategy: str
    ring_timeout_seconds: int
    max_wait_seconds: int
    wrapup_seconds: int
    announce_position: bool
    overflow_destination: str | None
    is_active: bool
    agents: list[AgentSummary]


class AgentCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)
    extension: str
    user_id: int | None = None

    @field_validator("extension")
    @classmethod
    def _extension(cls, value: str) -> str:
        value = value.strip()
        if not EXTENSION_RE.match(value):
            raise ValueError("extension: 2 to 6 digits")
        return value


class AgentUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: int | None = None
    is_active: bool | None = None


class AgentResponse(BaseModel):
    id: int
    display_name: str
    extension: str
    sip_username: str
    user_id: int | None
    is_active: bool
    queues: list[str]


class SoftphoneCredentials(BaseModel):
    """Shown once at creation or reset: the clear password is never stored."""

    agent: AgentResponse
    sip_username: str
    sip_password: str
    sip_realm: str
    wss_url: str | None


def _queue_response(queue: ContactCenterQueueModel) -> QueueResponse:
    return QueueResponse(
        id=queue.id,
        slug=queue.slug,
        name=queue.name,
        transfer_destination=f"queue:{queue.slug}",
        strategy=queue.strategy,
        ring_timeout_seconds=queue.ring_timeout_seconds,
        max_wait_seconds=queue.max_wait_seconds,
        wrapup_seconds=queue.wrapup_seconds,
        announce_position=queue.announce_position,
        overflow_destination=queue.overflow_destination,
        is_active=queue.is_active,
        agents=[
            AgentSummary(id=a.id, display_name=a.display_name, extension=a.extension)
            for a in sorted(queue.agents, key=lambda a: a.extension)
        ],
    )


def _agent_response(agent: ContactCenterAgentModel) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        display_name=agent.display_name,
        extension=agent.extension,
        sip_username=agent.sip_username,
        user_id=agent.user_id,
        is_active=agent.is_active,
        queues=sorted(q.slug for q in agent.queues),
    )


async def _org(user: UserModel) -> int:
    organization_id = user.selected_organization_id
    if not organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    if not await check_feature(organization_id, FEATURE_CONTACT_CENTER):
        raise HTTPException(
            status_code=402,
            detail="Your plan does not include the human contact center.",
        )
    return organization_id


async def _validate_member_user(organization_id: int, user_id: int | None) -> None:
    if user_id is None:
        return
    if not await db_client.is_user_member_of_organization(
        user_id=user_id, organization_id=organization_id
    ):
        raise HTTPException(status_code=422, detail="User is not in this organization")


# ----------------------------------------------------------------- queues
@router.get("/queues", response_model=list[QueueResponse])
async def list_queues(user: UserModel = Depends(get_user)):
    organization_id = await _org(user)
    return [
        _queue_response(q)
        for q in await db_client.list_contact_center_queues(organization_id)
    ]


@router.post("/queues", response_model=QueueResponse, status_code=201)
async def create_queue(
    request: QueueCreateRequest, user: UserModel = Depends(get_user)
):
    organization_id = await _org(user)
    if await db_client.get_contact_center_queue_by_slug(organization_id, request.slug):
        raise HTTPException(status_code=409, detail="A queue with this slug exists")
    try:
        queue = await db_client.create_contact_center_queue(
            organization_id,
            request.slug,
            request.model_dump(exclude={"slug", "agent_ids"}),
        )
    except ContactCenterConflict:
        raise HTTPException(status_code=409, detail="A queue with this slug exists")
    if request.agent_ids:
        try:
            queue = await db_client.set_contact_center_queue_members(
                organization_id, queue.id, request.agent_ids
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    await regenerate_asterisk_config()
    return _queue_response(queue)


@router.patch("/queues/{queue_id}", response_model=QueueResponse)
async def update_queue(
    queue_id: int, request: QueueUpdateRequest, user: UserModel = Depends(get_user)
):
    organization_id = await _org(user)
    fields = request.model_dump(exclude_unset=True, exclude={"agent_ids"})
    queue = await db_client.update_contact_center_queue(
        organization_id, queue_id, fields
    )
    if queue is None:
        raise HTTPException(status_code=404, detail="Queue not found")
    if request.agent_ids is not None:
        try:
            queue = await db_client.set_contact_center_queue_members(
                organization_id, queue_id, request.agent_ids
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    await regenerate_asterisk_config()
    return _queue_response(queue)


@router.delete("/queues/{queue_id}", status_code=204)
async def delete_queue(queue_id: int, user: UserModel = Depends(get_user)):
    organization_id = await _org(user)
    if not await db_client.delete_contact_center_queue(organization_id, queue_id):
        raise HTTPException(status_code=404, detail="Queue not found")
    await regenerate_asterisk_config()


# ----------------------------------------------------------------- agents
@router.get("/agents", response_model=list[AgentResponse])
async def list_agents(user: UserModel = Depends(get_user)):
    organization_id = await _org(user)
    return [
        _agent_response(a)
        for a in await db_client.list_contact_center_agents(organization_id)
    ]


@router.post("/agents", response_model=SoftphoneCredentials, status_code=201)
async def create_agent(
    request: AgentCreateRequest, user: UserModel = Depends(get_user)
):
    organization_id = await _org(user)
    await enforce_human_seat_limit(organization_id)
    await _validate_member_user(organization_id, request.user_id)
    credentials = new_agent_credentials(organization_id, request.extension)
    try:
        agent = await db_client.create_contact_center_agent(
            organization_id,
            display_name=sanitize_display_name(request.display_name),
            extension=request.extension,
            sip_username=credentials.sip_username,
            sip_md5_cred=credentials.md5_cred,
            user_id=request.user_id,
        )
    except ContactCenterConflict:
        raise HTTPException(status_code=409, detail="Extension already in use")
    await regenerate_asterisk_config()
    return SoftphoneCredentials(
        agent=_agent_response(agent),
        sip_username=credentials.sip_username,
        sip_password=credentials.password,
        sip_realm=ASTERISK_SIP_REALM,
        wss_url=ASTERISK_WSS_URL,
    )


@router.patch("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: int, request: AgentUpdateRequest, user: UserModel = Depends(get_user)
):
    organization_id = await _org(user)
    fields = request.model_dump(exclude_unset=True)
    if "display_name" in fields:
        fields["display_name"] = sanitize_display_name(fields["display_name"])
    if fields.get("user_id") is not None:
        await _validate_member_user(organization_id, fields["user_id"])
    if fields.get("is_active"):
        current = await db_client.get_contact_center_agent(organization_id, agent_id)
        if current is not None and not current.is_active:
            await enforce_human_seat_limit(organization_id)
    agent = await db_client.update_contact_center_agent(
        organization_id, agent_id, fields
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await regenerate_asterisk_config()
    return _agent_response(agent)


@router.post("/agents/{agent_id}/reset-password", response_model=SoftphoneCredentials)
async def reset_agent_password(agent_id: int, user: UserModel = Depends(get_user)):
    organization_id = await _org(user)
    agent = await db_client.get_contact_center_agent(organization_id, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    credentials = new_agent_credentials(organization_id, agent.extension)
    agent = await db_client.update_contact_center_agent(
        organization_id, agent_id, {"sip_md5_cred": credentials.md5_cred}
    )
    await regenerate_asterisk_config()
    return SoftphoneCredentials(
        agent=_agent_response(agent),
        sip_username=credentials.sip_username,
        sip_password=credentials.password,
        sip_realm=ASTERISK_SIP_REALM,
        wss_url=ASTERISK_WSS_URL,
    )


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: int, user: UserModel = Depends(get_user)):
    organization_id = await _org(user)
    if not await db_client.delete_contact_center_agent(organization_id, agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    await regenerate_asterisk_config()


@router.post("/agents/{agent_id}/claim", response_model=AgentResponse)
async def claim_agent_seat(agent_id: int, user: UserModel = Depends(get_user)):
    """Link an unassigned seat to the signed-in user (to use its softphone)."""
    organization_id = await _org(user)
    agent = await db_client.get_contact_center_agent(organization_id, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id not in (None, user.id):
        raise HTTPException(status_code=409, detail="This seat belongs to someone else")
    existing = await db_client.get_contact_center_agent_for_user(
        organization_id, user.id
    )
    if existing is not None and existing.id != agent_id:
        await db_client.update_contact_center_agent(
            organization_id, existing.id, {"user_id": None}
        )
    agent = await db_client.update_contact_center_agent(
        organization_id, agent_id, {"user_id": user.id}
    )
    return _agent_response(agent)


@router.get("/me", response_model=Optional[AgentResponse])
async def my_agent_seat(user: UserModel = Depends(get_user)):
    """The agent seat linked to the signed-in user, for the softphone page."""
    organization_id = await _org(user)
    agent = await db_client.get_contact_center_agent_for_user(organization_id, user.id)
    return _agent_response(agent) if agent else None


# --------------------------------------------------------------- handoffs
class HandoffResponse(BaseModel):
    id: str
    queue_slug: str | None
    caller_number: str | None
    status: str
    summary_status: str
    reason: str | None
    summary: str | None
    customer_name: str | None
    sentiment: str | None
    next_step: str | None
    collected_data: dict[str, Any]
    transcript: list[dict[str, Any]]
    workflow_run_id: int | None
    created_at: datetime | None
    answered_at: datetime | None


def _handoff_response(handoff: CallHandoffModel) -> HandoffResponse:
    return HandoffResponse(
        id=handoff.id,
        queue_slug=handoff.queue_slug,
        caller_number=handoff.caller_number,
        status=handoff.status,
        summary_status=handoff.summary_status,
        reason=handoff.reason,
        summary=handoff.summary,
        customer_name=handoff.customer_name,
        sentiment=handoff.sentiment,
        next_step=handoff.next_step,
        collected_data=handoff.collected_data or {},
        transcript=handoff.transcript or [],
        workflow_run_id=handoff.workflow_run_id,
        created_at=handoff.created_at,
        answered_at=handoff.answered_at,
    )


@router.get("/handoffs", response_model=list[HandoffResponse])
async def list_handoffs(
    mine: bool = False,
    status: Literal["pending", "answered"] | None = None,
    user: UserModel = Depends(get_user),
):
    """Recent AI -> human handoffs. ``mine`` keeps those of my seat's queues."""
    from api.services.contact_center.handoff import recent_cutoff

    organization_id = await _org(user)
    queue_slugs = None
    if mine:
        seat = await db_client.get_contact_center_agent_for_user(
            organization_id, user.id
        )
        queue_slugs = (
            await db_client.list_queue_slugs_for_agent(organization_id, seat.id)
            if seat
            else []
        )
    handoffs = await db_client.list_call_handoffs(
        organization_id,
        queue_slugs=queue_slugs,
        status=status,
        since=recent_cutoff() if mine else None,
    )
    return [_handoff_response(h) for h in handoffs]


@router.get("/handoffs/{handoff_id}", response_model=HandoffResponse)
async def get_handoff(handoff_id: str, user: UserModel = Depends(get_user)):
    organization_id = await _org(user)
    handoff = await db_client.get_call_handoff(organization_id, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return _handoff_response(handoff)


@router.post("/handoffs/{handoff_id}/accept", response_model=HandoffResponse)
async def accept_handoff(handoff_id: str, user: UserModel = Depends(get_user)):
    """The human agent picked up the call this card describes."""
    organization_id = await _org(user)
    handoff = await db_client.get_call_handoff(organization_id, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff not found")
    if handoff.status != "pending":
        return _handoff_response(handoff)
    seat = await db_client.get_contact_center_agent_for_user(organization_id, user.id)
    handoff = await db_client.update_call_handoff(
        organization_id,
        handoff_id,
        {
            "status": "answered",
            "answered_at": datetime.now(UTC),
            "answered_by_agent_id": seat.id if seat else None,
        },
    )
    return _handoff_response(handoff)


# -------------------------------------------------------------- callbacks
CallbackStatus = Literal["pending", "in_progress", "done", "failed", "canceled"]


class CallbackResponse(BaseModel):
    id: int
    phone: str
    customer_name: str | None
    reason: str | None
    source: str
    assign_to: str
    queue_slug: str | None
    workflow_id: int | None
    status: str
    scheduled_at: datetime
    attempts: int
    max_attempts: int
    last_attempt_at: datetime | None
    origin_workflow_run_id: int | None
    callback_workflow_run_id: int | None
    handoff_id: str | None
    assigned_agent_id: int | None
    outcome: str | None
    notes: str | None
    created_at: datetime | None
    completed_at: datetime | None


def _callback_response(callback) -> CallbackResponse:
    return CallbackResponse.model_validate(callback, from_attributes=True)


class CreateCallbackRequest(BaseModel):
    phone: str = Field(min_length=3, max_length=32)
    customer_name: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)
    scheduled_at: datetime | None = None
    assign_to: Literal["human", "ai"] = "human"
    queue_slug: str | None = Field(default=None, max_length=48)
    workflow_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)


class UpdateCallbackRequest(BaseModel):
    customer_name: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)
    scheduled_at: datetime | None = None
    assign_to: Literal["human", "ai"] | None = None
    queue_slug: str | None = Field(default=None, max_length=48)
    workflow_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)
    status: Literal["pending", "done", "failed", "canceled"] | None = None
    outcome: str | None = Field(default=None, max_length=1000)


async def _check_callback_targets(
    organization_id: int, queue_slug: str | None, workflow_id: int | None
) -> None:
    if queue_slug and not await db_client.get_contact_center_queue_by_slug(
        organization_id, queue_slug
    ):
        raise HTTPException(status_code=404, detail="Queue not found")
    if workflow_id and not await db_client.get_workflow(
        workflow_id, organization_id=organization_id
    ):
        raise HTTPException(status_code=404, detail="Agent not found")


async def _get_callback_or_404(organization_id: int, callback_id: int):
    callback = await db_client.get_callback_request(organization_id, callback_id)
    if callback is None:
        raise HTTPException(status_code=404, detail="Callback not found")
    return callback


@router.get("/callbacks", response_model=list[CallbackResponse])
async def list_callbacks(
    view: Literal["open", "closed", "all"] = "open",
    mine: bool = False,
    user: UserModel = Depends(get_user),
):
    """Callbacks to make (open) or made (closed).

    ``mine`` keeps the human callbacks of my seat's queues (and unrouted ones).
    """
    organization_id = await _org(user)
    statuses = {
        "open": ["pending", "in_progress"],
        "closed": ["done", "failed", "canceled"],
        "all": None,
    }[view]
    callbacks = await db_client.list_callback_requests(
        organization_id, statuses=statuses, limit=200
    )
    if mine:
        seat = await db_client.get_contact_center_agent_for_user(
            organization_id, user.id
        )
        slugs = (
            set(await db_client.list_queue_slugs_for_agent(organization_id, seat.id))
            if seat
            else set()
        )
        callbacks = [
            c
            for c in callbacks
            if c.assign_to == "human"
            and (c.queue_slug is None or c.queue_slug in slugs)
            and (c.assigned_agent_id in (None, seat.id if seat else None))
        ]
    return [_callback_response(c) for c in callbacks]


@router.post("/callbacks", response_model=CallbackResponse, status_code=201)
async def create_callback(
    request: CreateCallbackRequest, user: UserModel = Depends(get_user)
):
    from api.services.contact_center.callbacks import (
        CallbackError,
        create_or_update_callback,
    )

    organization_id = await _org(user)
    await _check_callback_targets(
        organization_id, request.queue_slug, request.workflow_id
    )
    scheduled_at = request.scheduled_at or datetime.now(UTC)
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    try:
        callback = await create_or_update_callback(
            organization_id,
            phone=request.phone,
            scheduled_at=scheduled_at,
            source="manual",
            assign_to=request.assign_to,
            reason=request.reason,
            customer_name=request.customer_name,
            queue_slug=request.queue_slug,
            workflow_id=request.workflow_id if request.assign_to == "ai" else None,
            notes=request.notes,
        )
    except CallbackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _callback_response(callback)


@router.patch("/callbacks/{callback_id}", response_model=CallbackResponse)
async def update_callback(
    callback_id: int,
    request: UpdateCallbackRequest,
    user: UserModel = Depends(get_user),
):
    """Reschedule, reassign, annotate or close a callback."""
    organization_id = await _org(user)
    callback = await _get_callback_or_404(organization_id, callback_id)
    fields = request.model_dump(exclude_unset=True)
    await _check_callback_targets(
        organization_id, fields.get("queue_slug"), fields.get("workflow_id")
    )
    assign_to = fields.get("assign_to", callback.assign_to)
    workflow_id = fields.get("workflow_id", callback.workflow_id)
    if assign_to == "ai" and not workflow_id:
        raise HTTPException(
            status_code=400, detail="An AI callback needs the agent that will call"
        )
    if fields.get("scheduled_at") and fields["scheduled_at"].tzinfo is None:
        fields["scheduled_at"] = fields["scheduled_at"].replace(tzinfo=UTC)
    status = fields.get("status")
    if status in {"done", "failed", "canceled"}:
        fields["completed_at"] = datetime.now(UTC)
    elif status == "pending":
        fields["completed_at"] = None
        fields["assigned_agent_id"] = None
        if callback.status in {"failed", "canceled", "done"}:
            fields["attempts"] = 0
    callback = await db_client.update_callback_request(
        organization_id, callback_id, fields
    )
    return _callback_response(callback)


@router.post("/callbacks/{callback_id}/dial", response_model=CallbackResponse)
async def dial_callback(callback_id: int, user: UserModel = Depends(get_user)):
    """Click-to-call: ring my softphone, then the customer once I answer."""
    from api.services.contact_center.callbacks import (
        CallbackError,
        dial_callback_for_agent,
    )

    organization_id = await _org(user)
    callback = await _get_callback_or_404(organization_id, callback_id)
    seat = await db_client.get_contact_center_agent_for_user(organization_id, user.id)
    if seat is None or not seat.is_active:
        raise HTTPException(
            status_code=403, detail="Claim a softphone seat to call customers back"
        )
    if callback.assign_to != "human":
        raise HTTPException(status_code=409, detail="This callback is for an AI agent")
    now = datetime.now(UTC)
    claimed = await db_client.claim_callback_request(
        organization_id,
        callback_id,
        fields={
            "status": "in_progress",
            "assigned_agent_id": seat.id,
            "attempts": callback.attempts + 1,
            "last_attempt_at": now,
        },
    )
    if claimed is None:
        raise HTTPException(
            status_code=409, detail="Another agent is already calling this customer"
        )
    try:
        await dial_callback_for_agent(claimed, seat)
    except CallbackError as exc:
        await db_client.update_callback_request(
            organization_id,
            callback_id,
            {
                "status": "pending",
                "assigned_agent_id": None,
                "attempts": callback.attempts,
            },
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        await db_client.update_callback_request(
            organization_id,
            callback_id,
            {
                "status": "pending",
                "assigned_agent_id": None,
                "attempts": callback.attempts,
            },
        )
        raise HTTPException(
            status_code=503, detail="The telephony server could not be reached"
        ) from exc
    return _callback_response(claimed)


class CompleteCallbackRequest(BaseModel):
    result: Literal["reached", "no_answer", "wrong_number"]
    outcome: str | None = Field(default=None, max_length=1000)
    retry_in_minutes: int | None = Field(default=None, ge=5, le=10080)


@router.post("/callbacks/{callback_id}/complete", response_model=CallbackResponse)
async def complete_callback(
    callback_id: int,
    request: CompleteCallbackRequest,
    user: UserModel = Depends(get_user),
):
    """The agent reports how the callback went."""
    from datetime import timedelta

    organization_id = await _org(user)
    callback = await _get_callback_or_404(organization_id, callback_id)
    now = datetime.now(UTC)
    labels = {
        "reached": "Client joint",
        "no_answer": "Pas de réponse",
        "wrong_number": "Mauvais numéro",
    }
    outcome = labels[request.result] + (
        f" — {request.outcome}" if request.outcome else ""
    )
    if request.result == "no_answer" and callback.attempts < callback.max_attempts:
        fields = {
            "status": "pending",
            "assigned_agent_id": None,
            "outcome": outcome,
            "scheduled_at": now + timedelta(minutes=request.retry_in_minutes or 60),
        }
    else:
        fields = {
            "status": "done" if request.result == "reached" else "failed",
            "outcome": outcome,
            "completed_at": now,
        }
    callback = await db_client.update_callback_request(
        organization_id, callback_id, fields
    )
    return _callback_response(callback)

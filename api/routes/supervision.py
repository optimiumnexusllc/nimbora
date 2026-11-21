"""Live supervision console: AI calls, queues, agents — and acting on them."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.constants import CONTACT_CENTER_ENABLED
from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.supervision import asterisk_live, live_calls

router = APIRouter(prefix="/supervision", tags=["supervision"])


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_organization_id


class SupervisionSnapshot(BaseModel):
    ai_calls: list[dict[str, Any]]
    agents: list[dict[str, Any]]
    queues: list[dict[str, Any]]
    waiting_callers: list[dict[str, Any]]
    kpis: dict[str, int]
    telephony: str
    contact_center_enabled: bool
    my_seat: dict[str, Any] | None


@router.get("", response_model=SupervisionSnapshot)
async def snapshot(user: UserModel = Depends(get_user)):
    """Everything happening right now in the organization (poll every few s)."""
    organization_id = _org(user)
    try:
        ai_calls = await live_calls.list_live_calls(organization_id)
    except Exception:
        ai_calls = []
    human: dict[str, Any] = {
        "agents": [],
        "queues": [],
        "waiting_callers": [],
        "busy_agents": 0,
        "telephony": "disabled",
    }
    my_seat = None
    if CONTACT_CENTER_ENABLED:
        agents = await db_client.list_contact_center_agents(organization_id)
        queues = await db_client.list_contact_center_queues(organization_id)
        human = await asterisk_live.human_snapshot(organization_id, agents, queues)
        seat = next((a for a in agents if a.user_id == user.id), None)
        if seat is not None:
            my_seat = {
                "id": seat.id,
                "is_supervisor": bool(seat.is_supervisor),
                "presence": seat.presence,
            }
    open_callbacks = await db_client.count_open_callback_requests(organization_id)
    agents_rows = human["agents"]
    kpis = {
        "ai_calls": len(ai_calls),
        "human_calls": human["busy_agents"],
        "waiting": sum(q["waiting"] for q in human["queues"]),
        "longest_wait_seconds": max(
            [q["longest_wait_seconds"] for q in human["queues"]] or [0]
        ),
        "agents_available": sum(1 for a in agents_rows if a["status"] == "available"),
        "agents_on_call": sum(1 for a in agents_rows if a["status"] == "on_call"),
        "agents_paused": sum(1 for a in agents_rows if a["status"] == "paused"),
        "callbacks_pending": open_callbacks,
    }
    return SupervisionSnapshot(
        ai_calls=ai_calls,
        agents=agents_rows,
        queues=human["queues"],
        waiting_callers=human["waiting_callers"],
        kpis=kpis,
        telephony=human["telephony"],
        contact_center_enabled=CONTACT_CENTER_ENABLED,
        my_seat=my_seat,
    )


async def _owned_run(organization_id: int, run_id: int):
    run = await db_client.get_workflow_run(run_id, organization_id=organization_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return run


@router.get("/calls/{run_id}/events")
async def call_events(
    run_id: int, after: int = 0, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """The live feed of one AI call: everything after event #``after``."""
    organization_id = _org(user)
    await _owned_run(organization_id, run_id)
    events = await live_calls.read_events(run_id, after=after)
    return {
        "events": events,
        "live": await live_calls.is_live(organization_id, run_id),
    }


class CallActionRequest(BaseModel):
    action: Literal["instruct", "say", "takeover", "hangup"]
    text: str | None = Field(default=None, max_length=500)
    queue_slug: str | None = Field(default=None, max_length=48)


@router.post("/calls/{run_id}/actions")
async def call_action(
    run_id: int, request: CallActionRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Steer a live AI call (delivered to the worker holding it)."""
    organization_id = _org(user)
    await _owned_run(organization_id, run_id)
    if request.action in {"instruct", "say"} and not (request.text or "").strip():
        raise HTTPException(status_code=400, detail="Text is required")
    if request.action == "takeover":
        if not request.queue_slug:
            raise HTTPException(
                status_code=400, detail="Choose the queue to transfer to"
            )
        if not await db_client.get_contact_center_queue_by_slug(
            organization_id, request.queue_slug
        ):
            raise HTTPException(status_code=404, detail="Queue not found")
    if not await live_calls.is_live(organization_id, run_id):
        raise HTTPException(status_code=409, detail="This call has ended")
    delivered = await live_calls.send_command(
        run_id,
        {
            **request.model_dump(),
            "by": user.email if hasattr(user, "email") else str(user.id),
        },
    )
    if not delivered:
        raise HTTPException(status_code=409, detail="This call has ended")
    return {"status": "sent"}


class SpyRequest(BaseModel):
    agent_id: int
    mode: Literal["listen", "whisper", "barge"] = "listen"


@router.post("/spy")
async def spy(
    request: SpyRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Listen to, whisper to, or join an agent's call (rings your softphone)."""
    if not CONTACT_CENTER_ENABLED:
        raise HTTPException(status_code=404, detail="Contact center is not enabled")
    organization_id = _org(user)
    seat = await db_client.get_contact_center_agent_for_user(organization_id, user.id)
    if seat is None or not seat.is_active:
        raise HTTPException(status_code=403, detail="Claim a softphone seat first")
    if not seat.is_supervisor:
        raise HTTPException(
            status_code=403, detail="Your seat does not have supervisor rights"
        )
    target = await db_client.get_contact_center_agent(organization_id, request.agent_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        await asterisk_live.start_spy(
            supervisor_seat=seat, target_agent=target, mode=request.mode
        )
    except asterisk_live.SupervisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="The telephony server could not be reached"
        ) from exc
    return {"status": "ringing", "mode": request.mode}

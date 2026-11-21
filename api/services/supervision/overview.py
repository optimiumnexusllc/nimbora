"""What the supervision console shows: AI calls and the built-in contact
center (agents, queues, waiting callers, KPIs)."""

from __future__ import annotations

from typing import Any

from api.constants import CONTACT_CENTER_ENABLED
from api.db import db_client
from api.services.supervision import asterisk_live, live_calls


async def snapshot(organization_id: int, user_id: int) -> dict[str, Any]:
    """Everything happening right now in the organization."""
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
        seat = next((a for a in agents if a.user_id == user_id), None)
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
    return {
        "ai_calls": ai_calls,
        "agents": agents_rows,
        "queues": human["queues"],
        "waiting_callers": human["waiting_callers"],
        "kpis": kpis,
        "telephony": human["telephony"],
        "contact_center_enabled": CONTACT_CENTER_ENABLED,
        "my_seat": my_seat,
    }

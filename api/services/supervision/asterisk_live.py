"""The human side of the contact center, live, from Asterisk ARI.

One snapshot per request (two ARI calls: channels and PJSIP endpoints),
filtered to one tenant by NIMBORA's naming rules:

* agent endpoints are ``t{org}_{extension}``;
* callers waiting in (or answered from) a queue sit on the ``;2`` half of
  ``Local/t{org}-{slug}@nimbora-queues``.

Supervisors can then listen, whisper or barge in on an agent's call:
ARI rings the supervisor's own softphone into a dialplan context that runs
``ChanSpy`` on that one agent (see ``asterisk_config``).
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

import aiohttp
from api.constants import ASTERISK_ARI_PASSWORD, ASTERISK_ARI_URL, ASTERISK_ARI_USER
from loguru import logger

SPY_MODES = {
    # q: no beep/announce, d: DTMF 4/5/6 switch modes, E: stop with the call
    "listen": "qdE",
    "whisper": "qdwE",
    "barge": "qdBE",
}
_QUEUE_CHANNEL_RE = re.compile(
    r"^Local/t(\d+)-([a-z0-9][a-z0-9-]*)@nimbora-queues-[^;]+;2$"
)


class SupervisionError(RuntimeError):
    pass


def ari_configured() -> bool:
    return bool(ASTERISK_ARI_PASSWORD)


async def _ari_get(path: str) -> Any:
    auth = aiohttp.BasicAuth(ASTERISK_ARI_USER, ASTERISK_ARI_PASSWORD or "")
    async with aiohttp.ClientSession(
        auth=auth, timeout=aiohttp.ClientTimeout(total=3)
    ) as session:
        async with session.get(f"{ASTERISK_ARI_URL.rstrip('/')}{path}") as response:
            if response.status >= 300:
                raise SupervisionError(f"Asterisk answered {response.status}")
            return await response.json()


def _seconds_since(iso: str | None, now: float) -> int:
    if not iso:
        return 0
    try:
        # Asterisk: 2026-11-21T04:30:12.345+0100
        parsed = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        try:
            parsed = datetime.fromisoformat(iso)
        except ValueError:
            return 0
    return max(0, int(now - parsed.timestamp()))


def build_snapshot(
    organization_id: int,
    channels: list[dict],
    endpoints: list[dict],
    agents: list[Any],
    queues: list[Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Pure function: ARI data + the tenant's seats/queues -> console view."""
    now = now or time.time()
    by_id = {c.get("id"): c for c in channels}
    endpoint_state = {
        e.get("resource"): e
        for e in endpoints
        if e.get("technology", "PJSIP") == "PJSIP"
    }
    prefix = f"t{organization_id}_"

    agent_rows = []
    busy_agents = 0
    for agent in agents:
        username = agent.sip_username
        if not username.startswith(prefix):
            continue  # never another tenant's seat
        endpoint = endpoint_state.get(username) or {}
        registered = endpoint.get("state") == "online"
        calls = [by_id[c] for c in endpoint.get("channel_ids") or [] if c in by_id]
        # Also catch channels the endpoint list has not caught up with.
        calls += [
            c
            for c in channels
            if c.get("name", "").startswith(f"PJSIP/{username}-") and c not in calls
        ]
        active = next((c for c in calls if c.get("state") == "Up"), None)
        ringing = next(
            (c for c in calls if c.get("state") in {"Ring", "Ringing"}), None
        )
        if not agent.is_active:
            status = "disabled"
        elif active:
            status = "on_call"
        elif ringing:
            status = "ringing"
        elif not registered:
            status = "offline"
        else:
            status = agent.presence or "available"
        if active:
            busy_agents += 1
        current = active or ringing
        connected = (current or {}).get("connected") or {}
        agent_rows.append(
            {
                "id": agent.id,
                "display_name": agent.display_name,
                "extension": agent.extension,
                "registered": registered,
                "presence": agent.presence or "available",
                "presence_reason": agent.presence_reason,
                "presence_since": agent.presence_changed_at.isoformat()
                if agent.presence_changed_at
                else None,
                "is_supervisor": bool(agent.is_supervisor),
                "status": status,
                "call": {
                    "with_number": connected.get("number") or "",
                    "with_name": connected.get("name") or "",
                    "seconds": _seconds_since(current.get("creationtime"), now),
                }
                if current
                else None,
            }
        )

    queue_rows = {
        q.slug: {
            "slug": q.slug,
            "name": q.name,
            "max_wait_seconds": q.max_wait_seconds,
            "waiting": 0,
            "longest_wait_seconds": 0,
            "in_conversation": 0,
            "available_agents": 0,
        }
        for q in queues
    }
    waiting_callers = []
    for channel in channels:
        match = _QUEUE_CHANNEL_RE.match(channel.get("name", ""))
        if not match or int(match.group(1)) != organization_id:
            continue
        slug = match.group(2)
        row = queue_rows.get(slug)
        if row is None:
            continue
        app = ((channel.get("dialplan") or {}).get("app_name") or "").lower()
        seconds = _seconds_since(channel.get("creationtime"), now)
        caller = channel.get("caller") or {}
        if app == "queue":
            row["waiting"] += 1
            row["longest_wait_seconds"] = max(row["longest_wait_seconds"], seconds)
            waiting_callers.append(
                {
                    "queue_slug": slug,
                    "number": caller.get("number") or "",
                    "name": caller.get("name") or "",
                    "seconds": seconds,
                }
            )
        else:
            row["in_conversation"] += 1
    for queue in queues:
        members = {a.id for a in getattr(queue, "agents", []) or []}
        queue_rows[queue.slug]["available_agents"] = sum(
            1 for a in agent_rows if a["id"] in members and a["status"] == "available"
        )

    return {
        "agents": agent_rows,
        "queues": list(queue_rows.values()),
        "waiting_callers": sorted(waiting_callers, key=lambda w: -w["seconds"]),
        "busy_agents": busy_agents,
    }


async def human_snapshot(organization_id: int, agents: list, queues: list) -> dict:
    if not ari_configured():
        snapshot = build_snapshot(organization_id, [], [], agents, queues)
        return {**snapshot, "telephony": "not_configured"}
    try:
        channels = await _ari_get("/channels")
        endpoints = await _ari_get("/endpoints/PJSIP")
    except Exception as exc:
        logger.warning(f"Supervision: Asterisk unreachable ({exc})")
        snapshot = build_snapshot(organization_id, [], [], agents, queues)
        return {**snapshot, "telephony": "unreachable"}
    snapshot = build_snapshot(organization_id, channels, endpoints, agents, queues)
    return {**snapshot, "telephony": "ok"}


async def start_spy(*, supervisor_seat, target_agent, mode: str) -> str:
    """Ring the supervisor's softphone into a ChanSpy session on one agent."""
    if mode not in SPY_MODES:
        raise SupervisionError("mode must be listen, whisper or barge")
    if supervisor_seat.organization_id != target_agent.organization_id:
        raise SupervisionError("Agent of another organization")
    if supervisor_seat.id == target_agent.id:
        raise SupervisionError("You cannot supervise your own seat")
    if not ari_configured():
        raise SupervisionError("The platform telephony (Asterisk) is not configured")
    from api.services.contact_center.asterisk_config import SUPERVISE_DIALPLAN_CONTEXT

    labels = {"listen": "Écoute", "whisper": "Chuchotement", "barge": "Intervention"}
    params = {
        "endpoint": f"PJSIP/{supervisor_seat.sip_username}",
        "context": SUPERVISE_DIALPLAN_CONTEXT,
        "extension": "spy",
        "priority": 1,
        "callerId": f'"{labels[mode]} {target_agent.display_name[:24]}" <{target_agent.extension}>',
        "timeout": 30,
    }
    body = {
        "variables": {
            # Trailing dash: PJSIP/t3_2001- never matches PJSIP/t3_20011-…
            "NIMBORA_SPY_TARGET": f"PJSIP/{target_agent.sip_username}-",
            "NIMBORA_SPY_OPTIONS": SPY_MODES[mode],
        }
    }
    auth = aiohttp.BasicAuth(ASTERISK_ARI_USER, ASTERISK_ARI_PASSWORD or "")
    async with aiohttp.ClientSession(
        auth=auth, timeout=aiohttp.ClientTimeout(total=10)
    ) as session:
        async with session.post(
            f"{ASTERISK_ARI_URL.rstrip('/')}/channels", params=params, json=body
        ) as response:
            if response.status >= 300:
                raise SupervisionError(f"Asterisk refused the call ({response.status})")
            data = await response.json()
            return data.get("id", "")

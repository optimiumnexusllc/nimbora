"""Supervision of the enterprise PBX: live queues, listening, statistics.

What a supervisor sees and can do on the human side of the call center, next
to the AI calls (``services.supervision``):

* **Live state** — queues with the callers waiting (AMI ``QueueStatus``
  through wazo-amid; the REST APIs do not expose waiting callers), agents
  (agentd) and the conversations in progress on each extension (calld).
* **Listening, whispering, barging** — calld rings the supervisor's own
  phone; once answered it runs ``ChanSpy`` on the target extension's channel
  in the ``nimbora-supervision`` dialplan context installed by the PBX kit
  (``deploy/pbx/nimbora-supervision.conf``). Off by default, enabled per
  organization only after confirming that staff have been informed; every
  session is logged.
* **Statistics** — call-logd's queue and agent statistics (answered rate,
  average wait, service level). The engine computes them every 6 hours.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from api.services.pbx.client import PbxError
from api.services.pbx.service import PbxRouteError, _connection, client_for

MODES = ("listen", "whisper", "barge")
# ChanSpy options. q: no beep or name announcement to the supervisor;
# E: stop when the spied channel hangs up; w: whisper (the agent hears the
# supervisor, the caller does not); B: barge (everybody hears everybody).
SPY_OPTIONS = {"listen": "qE", "whisper": "qwE", "barge": "qBE"}
DIALPLAN_CONTEXT = "nimbora-supervision"
DIALPLAN_EXTENSION = "spy"
MODE_LABELS = {"listen": "Écoute", "whisper": "Chuchotement", "barge": "Intervention"}
PERIODS = ("today", "yesterday", "7d", "30d")
DEFAULT_SLA_SECONDS = 20
LIVE_CACHE_SECONDS = 2.0
_ENDPOINT_NAME_RE = re.compile(r"^[A-Za-z0-9_.@+-]{1,80}$")

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "modes": list(MODES),
    "supervisors": [],  # PBX user uuids allowed to listen; empty: any extension
    "protected": [],  # PBX user uuids that are never listened to
    "notice_acknowledged": False,
    "sla_seconds": DEFAULT_SLA_SECONDS,
}

# org -> (wall time, live state): many supervisors share one PBX poll.
_live_cache: dict[int, tuple[float, dict[str, Any]]] = {}


# ---------------------------------------------------------------- settings


def read_settings(connection) -> dict[str, Any]:
    stored = connection.supervision_settings or {}
    settings = {**DEFAULT_SETTINGS, **stored}
    settings["modes"] = [m for m in settings.get("modes") or [] if m in MODES]
    return settings


async def save_settings(
    organization_id: int, payload: dict[str, Any], **client_kwargs
) -> dict[str, Any]:
    from api.db import db_client

    connection = await _connection(organization_id)
    settings = {**read_settings(connection), **payload}
    settings["modes"] = [m for m in MODES if m in (settings.get("modes") or [])]
    if settings["enabled"] and not settings["notice_acknowledged"]:
        raise PbxRouteError(
            "Confirmez d'abord que les collaborateurs ont été informés de "
            "l'écoute des appels.",
            422,
        )
    if settings["enabled"] and not settings["modes"]:
        raise PbxRouteError("Choisissez au moins un mode d'écoute.", 422)
    sla = int(settings.get("sla_seconds") or DEFAULT_SLA_SECONDS)
    if not 5 <= sla <= 600:
        raise PbxRouteError("Le seuil de qualité de service va de 5 à 600 s.", 422)
    settings["sla_seconds"] = sla
    wanted = set(settings["supervisors"]) | set(settings["protected"])
    if wanted:
        async with client_for(connection, **client_kwargs) as client:
            known = {u.get("uuid") for u in await client.users()}
        unknown = wanted - known
        if unknown:
            raise PbxRouteError("Poste inconnu sur le PBX de l'entreprise.", 422)
    settings["supervisors"] = sorted(set(settings["supervisors"]))
    settings["protected"] = sorted(set(settings["protected"]))
    await db_client.save_pbx_connection(
        organization_id, {"supervision_settings": settings}
    )
    _live_cache.pop(organization_id, None)
    return settings


# --------------------------------------------------------------- live state


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_queue_status(messages: list[dict], queue_name: str) -> dict[str, Any]:
    """Waiting callers and members of one queue, from the AMI event list."""
    waiting: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    params: dict[str, Any] = {}
    for message in messages:
        if message.get("Queue") != queue_name:
            continue  # the AMI is not tenant aware: never trust other queues
        event = message.get("Event")
        if event == "QueueParams":
            params = message
        elif event == "QueueEntry":
            waiting.append(
                {
                    "position": _int(message.get("Position"), len(waiting) + 1),
                    "number": message.get("CallerIDNum") or None,
                    "name": message.get("CallerIDName") or None,
                    "wait_seconds": _int(message.get("Wait")),
                }
            )
        elif event == "QueueMember":
            members.append(
                {
                    "name": message.get("Name"),
                    "in_call": message.get("InCall") == "1",
                    "paused": message.get("Paused") == "1",
                    "calls_taken": _int(message.get("CallsTaken")),
                }
            )
    for entry in waiting:
        if entry["number"] in ("<unknown>", "unknown"):
            entry["number"] = None
        if entry["name"] in ("<unknown>", "unknown"):
            entry["name"] = None
    waiting.sort(key=lambda w: w["position"])
    return {"waiting": waiting, "members": members, "params": params}


def _since_seconds(iso: str | None, now: datetime) -> int:
    if not iso:
        return 0
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0, int((now - moment).total_seconds()))


def _person(record: dict) -> str:
    return " ".join(
        p for p in (record.get("firstname"), record.get("lastname")) if p
    ).strip()


def other_party(call: dict, user: dict | None) -> tuple[str | None, str | None]:
    """The person the extension talks to (number, name).

    On an extension's leg, the engine's caller and connected-line identities
    swap with the call direction; whichever is not the extension is the
    other party.
    """
    own = {str(user.get("extension"))} if user and user.get("extension") else set()
    caller = (call.get("caller_id_number"), call.get("caller_id_name"))
    peer = (call.get("peer_caller_id_number"), call.get("peer_caller_id_name"))
    if peer[0] and str(peer[0]) not in own:
        return peer[0], peer[1] or None
    if caller[0] and str(caller[0]) not in own:
        return caller[0], caller[1] or None
    return peer[0] or caller[0], peer[1] or caller[1] or None


def _call_state(call: dict) -> str:
    status = str(call.get("status") or "").lower()
    if status in {"ringing", "ring", "down"} and not call.get("answer_time"):
        return "ringing"
    return "on_call"


async def live(
    organization_id: int,
    *,
    use_cache: bool = True,
    newer_than: float | None = None,
    **client_kwargs,
) -> dict[str, Any]:
    """Queues, agents and conversations right now. Each part fails alone.

    A state read less than ``LIVE_CACHE_SECONDS`` ago is reused, unless it
    is older than ``newer_than`` (the time of a PBX event): the first
    supervisor to react to an event refreshes it for everyone.
    """
    cached = _live_cache.get(organization_id)
    if (
        use_cache
        and cached
        and time.time() - cached[0] < LIVE_CACHE_SECONDS
        and (newer_than is None or cached[0] >= newer_than)
    ):
        return cached[1]
    read_at = time.time()
    connection = await _connection(organization_id)
    settings = read_settings(connection)
    result: dict[str, Any] = {}
    errors: dict[str, str] = {}

    async with client_for(connection, **client_kwargs) as client:

        async def section(name: str, coro):
            try:
                result[name] = await coro
            except PbxError as error:
                result[name] = []
                errors[name] = str(error)

        await asyncio.gather(
            section("users", client.users()),
            section("queues", client.queues()),
            section("agents", client.agents()),
            section("agent_statuses", client.agent_statuses()),
            section("calls", client.calls()),
        )

        queue_status: dict[str, dict[str, Any]] = {}

        async def one_queue(name: str):
            try:
                queue_status[name] = parse_queue_status(
                    await client.queue_status(name), name
                )
            except PbxError as error:
                errors["waiting"] = str(error)

        await asyncio.gather(
            *(one_queue(q["name"]) for q in result["queues"] if q.get("name"))
        )

    now = datetime.now(UTC)
    users = {u.get("uuid"): u for u in result["users"]}
    user_by_extension = {
        str(u.get("extension")): u for u in result["users"] if u.get("extension")
    }
    calls_by_user: dict[str, list[dict]] = {}
    for call in result["calls"]:
        if call.get("user_uuid"):
            calls_by_user.setdefault(call["user_uuid"], []).append(call)
    protected = set(settings["protected"])

    def call_row(call: dict, user: dict | None) -> dict[str, Any]:
        uuid = call.get("user_uuid")
        with_number, with_name = other_party(call, user)
        return {
            "call_id": call.get("call_id"),
            "user_uuid": uuid,
            "user_name": _person(user) if user else None,
            "extension": user.get("extension") if user else None,
            "with_number": with_number,
            "with_name": with_name,
            "direction": call.get("direction") or "unknown",
            "state": _call_state(call),
            "seconds": _since_seconds(
                call.get("answer_time") or call.get("creation_time"), now
            ),
            "on_hold": bool(call.get("on_hold")),
            "recording": call.get("record_state") == "active",
            "spyable": bool(
                settings["enabled"]
                and uuid
                and uuid not in protected
                and _call_state(call) == "on_call"
            ),
        }

    statuses = {s.get("id"): s for s in result["agent_statuses"]}
    agents: list[dict[str, Any]] = []
    for agent in result["agents"]:
        status = statuses.get(agent.get("id")) or {}
        extension = status.get("extension") or agent.get("number")
        user = user_by_extension.get(str(extension)) if extension else None
        calls = calls_by_user.get(user.get("uuid"), []) if user else []
        if not status.get("logged"):
            state = "logged_out"
        elif calls:
            state = _call_state(calls[0])
        elif status.get("paused"):
            state = "paused"
        else:
            state = "available"
        agents.append(
            {
                "id": agent.get("id"),
                "number": agent.get("number"),
                "name": _person(agent) or f"Agent {agent.get('number')}",
                "user_uuid": user.get("uuid") if user else None,
                "extension": extension,
                "state": state,
                "paused_reason": status.get("paused_reason")
                if status.get("paused")
                else None,
                "call": call_row(calls[0], user) if calls else None,
            }
        )
    agent_state = {a["id"]: a["state"] for a in agents}

    queues: list[dict[str, Any]] = []
    for queue in result["queues"]:
        member_ids = [
            m.get("id") for m in (queue.get("members") or {}).get("agents") or []
        ]
        states = [agent_state.get(i, "logged_out") for i in member_ids]
        status = queue_status.get(queue.get("name"))
        waiting = status["waiting"] if status else []
        queues.append(
            {
                "id": queue.get("id"),
                "name": queue.get("label") or queue.get("name"),
                "number": next(
                    (e.get("exten") for e in queue.get("extensions") or []), None
                ),
                "live": status is not None,
                "waiting": len(waiting),
                "longest_wait_seconds": max(
                    (w["wait_seconds"] for w in waiting), default=0
                ),
                "callers": waiting,
                "agents_available": states.count("available"),
                "agents_on_call": states.count("on_call") + states.count("ringing"),
                "agents_paused": states.count("paused"),
                "agents_logged": len(states) - states.count("logged_out"),
                "members": len(member_ids),
                "sla_seconds": settings["sla_seconds"],
            }
        )

    calls = [
        call_row(call, users.get(call.get("user_uuid")))
        for call in result["calls"]
        if call.get("user_uuid")
    ]
    calls.sort(key=lambda c: -c["seconds"])
    await _attach_handoff_cards(organization_id, queues, agents, calls)
    state = {
        "queues": queues,
        "agents": agents,
        "calls": calls,
        "kpis": {
            "calls": sum(1 for c in calls if c["state"] == "on_call"),
            "waiting": sum(q["waiting"] for q in queues),
            "longest_wait_seconds": max(
                (q["longest_wait_seconds"] for q in queues), default=0
            ),
            "agents_available": sum(1 for a in agents if a["state"] == "available"),
            "agents_on_call": sum(
                1 for a in agents if a["state"] in {"on_call", "ringing"}
            ),
            "agents_paused": sum(1 for a in agents if a["state"] == "paused"),
            "agents_logged_out": sum(1 for a in agents if a["state"] == "logged_out"),
        },
        "listening": {
            "enabled": settings["enabled"],
            "modes": settings["modes"],
            "supervisors": settings["supervisors"],
        },
        "errors": errors,
        "at": now.isoformat(),
    }
    _live_cache[organization_id] = (read_at, state)
    return state


async def _attach_handoff_cards(organization_id, queues, agents, calls) -> None:
    """Callers the AI handed over carry its card (reason, summary, mood)."""
    from api.services.pbx import handoff

    try:
        cards = await handoff.recent_cards(organization_id)
    except Exception:  # noqa: BLE001 - the live view never fails on cards
        logger.opt(exception=True).debug("Handoff cards not attached")
        return
    by_number: dict[str, dict[str, Any]] = {}
    for card in cards:  # newest first: keep the latest card per caller
        key = handoff.caller_key(card.caller_number)
        if key and key not in by_number and card.status in ("pending", "answered"):
            by_number[key] = {
                "id": card.id,
                "reason": card.reason,
                "summary": card.summary,
                "sentiment": card.sentiment,
                "next_step": card.next_step,
                "customer_name": card.customer_name,
            }
    if not by_number:
        return

    def card_for(number: Any) -> dict[str, Any] | None:
        key = handoff.caller_key(number)
        return by_number.get(key) if key else None

    for queue in queues:
        for caller in queue["callers"]:
            caller["handoff"] = card_for(caller["number"])
    for call in calls:
        call["handoff"] = card_for(call["with_number"])
    for agent in agents:
        if agent["call"]:
            agent["call"]["handoff"] = card_for(agent["call"]["with_number"])


def invalidate(organization_id: int) -> None:
    _live_cache.pop(organization_id, None)


# ------------------------------------------------------- listen / whisper


async def start_spy(
    organization_id: int,
    *,
    supervisor_user_uuid: str,
    target_user_uuid: str,
    mode: str,
    requested_by_user_id: int | None,
    **client_kwargs,
) -> dict[str, Any]:
    """Ring the supervisor's phone into a listening session on one extension."""
    from api.db import db_client

    if mode not in MODES:
        raise PbxRouteError("Mode inconnu.", 422)
    connection = await _connection(organization_id)
    settings = read_settings(connection)
    if not settings["enabled"]:
        raise PbxRouteError(
            "L'écoute des appels n'est pas activée pour cette entreprise "
            "(Supervision → Réglages de l'écoute).",
            409,
        )
    if mode not in settings["modes"]:
        raise PbxRouteError(f"Le mode « {MODE_LABELS[mode]} » n'est pas autorisé.", 403)
    if settings["supervisors"] and supervisor_user_uuid not in settings["supervisors"]:
        raise PbxRouteError("Ce poste n'est pas autorisé à écouter les appels.", 403)
    if target_user_uuid in settings["protected"]:
        raise PbxRouteError("Les appels de ce poste ne peuvent pas être écoutés.", 403)
    if supervisor_user_uuid == target_user_uuid:
        raise PbxRouteError("Vous ne pouvez pas écouter votre propre poste.", 409)

    async with client_for(connection, **client_kwargs) as client:
        try:
            target = await client.user(target_user_uuid)
            supervisor = await client.user(supervisor_user_uuid)
        except PbxError as error:
            if error.status == 404:
                raise PbxRouteError("Poste introuvable sur le PBX.", 404) from error
            raise
        calls = await client.calls()
        target_calls = [
            c
            for c in calls
            if c.get("user_uuid") == target_user_uuid and _call_state(c) == "on_call"
        ]
        if not target_calls:
            raise PbxRouteError("Ce poste n'est pas en communication.", 409)
        if any(c.get("user_uuid") == supervisor_user_uuid for c in calls):
            raise PbxRouteError(
                "Votre poste est déjà en communication : raccrochez d'abord.", 409
            )
        call = target_calls[0]
        lines = [
            line
            for line in target.get("lines") or []
            if (line.get("endpoint_sip") or {}).get("uuid")
        ]
        line = next((li for li in lines if li.get("id") == call.get("line_id")), None)
        line = line or (lines[0] if lines else None)
        if line is None:
            raise PbxRouteError("Ce poste n'a pas de ligne SIP à écouter.", 409)
        endpoint = await client.endpoint_sip(line["endpoint_sip"]["uuid"])
        name = str(endpoint.get("name") or "")
        if not _ENDPOINT_NAME_RE.fullmatch(name):
            raise PbxRouteError("Nom de ligne SIP inattendu sur le PBX.", 409)
        target_name = _person(target) or target.get("extension") or "poste"
        # Trailing dash: PJSIP/koffi- never matches PJSIP/koffi2-…
        originated = await client.originate(
            supervisor_user_uuid,
            context=DIALPLAN_CONTEXT,
            extension=DIALPLAN_EXTENSION,
            variables={
                "NIMBORA_SPY_TARGET": f"PJSIP/{name}-",
                "NIMBORA_SPY_OPTIONS": SPY_OPTIONS[mode],
                "NIMBORA_SPY_LABEL": f"{MODE_LABELS[mode]} {target_name}"[:40],
            },
        )

    session = await db_client.record_supervision_session(
        organization_id,
        {
            "requested_by_user_id": requested_by_user_id,
            "mode": mode,
            "supervisor_user_uuid": supervisor_user_uuid,
            "supervisor_name": (_person(supervisor) or None),
            "target_user_uuid": target_user_uuid,
            "target_name": target_name[:128],
            "target_extension": target.get("extension"),
            "call_id": (originated or {}).get("call_id"),
        },
    )
    logger.info(
        f"[PBX org={organization_id}] {mode} on {target_user_uuid} "
        f"by {supervisor_user_uuid} (session {session.id})"
    )
    return {
        "status": "ringing",
        "mode": mode,
        "session_id": session.id,
        "target_name": target_name,
    }


def serialize_session(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "mode": row.mode,
        "supervisor_name": row.supervisor_name,
        "supervisor_user_uuid": row.supervisor_user_uuid,
        "target_name": row.target_name,
        "target_extension": row.target_extension,
        "requested_by_user_id": row.requested_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_sessions(organization_id: int, limit: int = 50) -> list[dict[str, Any]]:
    from api.db import db_client

    rows = await db_client.list_supervision_sessions(organization_id, limit=limit)
    return [serialize_session(r) for r in rows]


async def extensions(organization_id: int, **client_kwargs) -> list[dict[str, Any]]:
    """The tenant's extensions (to pick one's own phone, list supervisors)."""
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        users = await client.users()
    rows = [
        {
            "uuid": u.get("uuid"),
            "name": _person(u) or u.get("email") or u.get("extension") or "—",
            "extension": u.get("extension"),
            "email": (u.get("email") or "").strip().lower() or None,
        }
        for u in users
        if u.get("uuid")
    ]
    rows.sort(key=lambda r: (r["extension"] or "~", r["name"]))
    return rows


# ---------------------------------------------------------------- statistics


def period_bounds(period: str, tz: str, now: datetime | None = None) -> tuple[str, str]:
    """Local ``from``/``until`` (ISO, no offset) for call-logd's ``timezone``."""
    if period not in PERIODS:
        raise PbxRouteError("Période inconnue.", 422)
    zone = ZoneInfo(tz)
    local_now = (now or datetime.now(UTC)).astimezone(zone)
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    starts = {
        "today": today,
        "yesterday": today - timedelta(days=1),
        "7d": today - timedelta(days=6),
        "30d": today - timedelta(days=29),
    }
    until = today if period == "yesterday" else today + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%S"
    return starts[period].strftime(fmt), until.strftime(fmt)


async def _timezone(organization_id: int) -> str:
    try:
        from api.services.business.profile import get_business_profile

        profile = await get_business_profile(organization_id)
        ZoneInfo(profile.timezone)
        return profile.timezone
    except Exception:  # noqa: BLE001 - statistics still work in UTC
        return "UTC"


def _rate(numerator: float, denominator: float) -> float | None:
    return round(100 * numerator / denominator, 1) if denominator else None


async def statistics(
    organization_id: int, period: str = "today", **client_kwargs
) -> dict[str, Any]:
    connection = await _connection(organization_id)
    settings = read_settings(connection)
    tz = await _timezone(organization_id)
    start, until = period_bounds(period, tz)
    params = {"from": start, "until": until, "timezone": tz}
    async with client_for(connection, **client_kwargs) as client:
        queue_items, agent_items, queues, agents = await asyncio.gather(
            client.queue_statistics(**params, qos_threshold=settings["sla_seconds"]),
            client.agent_statistics(**params),
            client.queues(),
            client.agents(),
        )
    queue_names = {q.get("id"): q.get("label") or q.get("name") for q in queues}
    agent_names = {
        a.get("id"): _person(a) or f"Agent {a.get('number')}" for a in agents
    }

    queue_rows = []
    for item in queue_items:
        received = _int(item.get("received"))
        closed = _int(item.get("closed"))
        answered = _int(item.get("answered"))
        queue_rows.append(
            {
                "queue_id": item.get("queue_id"),
                "name": queue_names.get(item.get("queue_id"))
                or item.get("queue_name")
                or "—",
                "received": received,
                "answered": answered,
                "abandoned": _int(item.get("abandoned")),
                "unanswered": _int(item.get("not_answered"))
                + _int(item.get("saturated"))
                + _int(item.get("blocked")),
                "closed": closed,
                "average_wait_seconds": _int(item.get("average_waiting_time")),
                "answered_rate": item.get("answered_rate")
                if item.get("answered_rate") is not None
                else _rate(answered, received - closed),
                "service_level": item.get("quality_of_service"),
            }
        )
    agent_rows = []
    for item in agent_items:
        answered = _int(item.get("answered"))
        talk = _int(item.get("conversation_time"))
        agent_rows.append(
            {
                "agent_id": item.get("agent_id"),
                "name": agent_names.get(item.get("agent_id"))
                or f"Agent {item.get('agent_number')}",
                "number": item.get("agent_number"),
                "answered": answered,
                "conversation_seconds": talk,
                "average_talk_seconds": talk // answered if answered else 0,
                "login_seconds": _int(item.get("login_time")),
                "pause_seconds": _int(item.get("pause_time")),
                "wrapup_seconds": _int(item.get("wrapup_time")),
                "occupancy": _rate(talk, _int(item.get("login_time"))),
            }
        )
    agent_rows.sort(key=lambda a: -a["answered"])

    received = sum(q["received"] for q in queue_rows)
    closed = sum(q["closed"] for q in queue_rows)
    answered = sum(q["answered"] for q in queue_rows)
    within_sla = sum(
        (q["service_level"] or 0) * q["answered"] / 100 for q in queue_rows
    )
    waited = sum(q["average_wait_seconds"] * q["answered"] for q in queue_rows)
    return {
        "period": period,
        "from": start,
        "until": until,
        "timezone": tz,
        "sla_seconds": settings["sla_seconds"],
        "queues": queue_rows,
        "agents": agent_rows,
        "totals": {
            "received": received,
            "answered": answered,
            "abandoned": sum(q["abandoned"] for q in queue_rows),
            "answered_rate": _rate(answered, received - closed),
            "service_level": _rate(within_sla, answered),
            "average_wait_seconds": round(waited / answered) if answered else 0,
        },
    }

"""Presence of the company's employees on the enterprise PBX.

One state per person, in the order a colleague cares about:

- ``on_call``: talking or holding a call;
- ``ringing``: a call is ringing or being placed;
- ``dnd``: do-not-disturb is on;
- ``away``: the person said so (« Absent »);
- ``offline``: no phone or app connected, or the person shows as unavailable;
- ``available``: ready to take a call.

The engine's presence service (chatd) gives all of it. A service account made
before NIMBORA asked for presence rights is refused by chatd: then the state
comes from the calls in progress alone (``on_call`` / ``ringing``, otherwise
``unknown``), so the directory keeps working.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from api.services.pbx.client import PbxClient, PbxError

STATES = ("available", "on_call", "ringing", "dnd", "away", "offline", "unknown")
LABELS = {
    "available": "Disponible",
    "on_call": "En appel",
    "ringing": "Sonne",
    "dnd": "Ne pas déranger",
    "away": "Absent",
    "offline": "Hors ligne",
    "unknown": "Inconnu",
}
# What an employee may set for themselves (the rest follows their phone).
# « Hors ligne » chosen by the person is sent as "invisible": the engine (26.11)
# leaves "unavailable" on users who never set a presence, so that state cannot
# mean anything any more (lab step 10).
SETTABLE = {"available": "available", "away": "away", "offline": "invisible"}


def from_engine(item: dict[str, Any]) -> str:
    """One state from a chatd presence item."""
    line = str(item.get("line_state") or "").lower()
    if line in {"talking", "holding"}:
        return "on_call"
    if line in {"ringing", "progressing"}:
        return "ringing"
    if item.get("do_not_disturb"):
        return "dnd"
    state = str(item.get("state") or "").lower()
    if state == "away":
        return "away"
    if state == "invisible":
        return "offline"
    # On the engine (26.11) a user who never set a chat presence stays
    # "unavailable" for ever, phone registered or not: the line decides.
    # Registered and idle → available; nothing registered, no app, no mobile
    # → offline.
    if line == "available":
        return "available"
    if item.get("connected") or item.get("mobile"):
        return "available"
    return "offline"


def from_calls(calls: list[dict[str, Any]]) -> dict[str, str]:
    """On-call / ringing users from the calls in progress (fallback)."""
    states: dict[str, str] = {}
    for call in calls:
        user = call.get("user_uuid")
        if not user:
            continue
        status = str(call.get("status") or "").lower()
        ringing = status in {"ringing", "ring", "down"} and not call.get("answer_time")
        if states.get(user) != "on_call":
            states[user] = "ringing" if ringing else "on_call"
    return states


def entry(state: str, status: str = "") -> dict[str, str]:
    return {"state": state, "label": LABELS.get(state, state), "status": status or ""}


async def team_presence(client: PbxClient) -> tuple[dict[str, dict[str, str]], bool]:
    """User uuid → presence, and whether it came from the presence service."""
    try:
        items = await client.presences()
    except PbxError as error:
        logger.info("PBX presence unavailable ({}), using calls in progress", error)
    else:
        return (
            {
                str(item["uuid"]): entry(from_engine(item), item.get("status") or "")
                for item in items
                if item.get("uuid")
            },
            True,
        )
    try:
        calls = await client.calls()
    except PbxError:
        calls = []
    return {user: entry(state) for user, state in from_calls(calls).items()}, False


def presence_of(presence: dict[str, dict[str, str]], user_uuid: str | None, live: bool):
    if user_uuid and user_uuid in presence:
        return presence[user_uuid]
    return entry("available" if live else "unknown")


async def set_my_presence(
    client: PbxClient, user_uuid: str, state: str, status: str = ""
) -> dict[str, str]:
    if state not in SETTABLE:
        raise ValueError(f"État inconnu : {state}")
    await client.set_presence(user_uuid, SETTABLE[state], status.strip()[:128])
    return entry(state, status.strip()[:128])


async def organization_presence(
    organization_id: int, **client_kwargs
) -> dict[str, Any]:
    """Presence of every extension of the company, for the console."""
    from api.services.pbx.service import _connection, client_for

    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        users = await client.users()
        presence, live = await team_presence(client)
    return {
        "live": live,
        "extensions": {
            str(u["extension"]): presence_of(presence, u.get("uuid"), live)
            for u in users
            if u.get("extension")
        },
    }

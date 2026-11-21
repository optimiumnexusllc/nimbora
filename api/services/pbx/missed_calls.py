"""Missed calls on the enterprise PBX, called back by an AI agent.

Each call log the PBX sends (webhook ``call_log_created``) is looked at once:

* **AI handoff cards** waiting for a human are closed: answered when a person
  took the call, abandoned otherwise — and an abandoned handoff is called
  back with what the AI had already learned (its reason and summary);
* **a customer served** (an answered call with them, either way) cancels the
  automatic callbacks still waiting for them: nobody calls back someone who
  already got through;
* **a missed inbound call** (a queue nobody answered, or any extension,
  depending on the policy) becomes a callback assigned to the chosen AI
  agent, after a delay and — if asked — at the next opening of the business.

The callbacks themselves are the platform's usual ones (``callbacks``): the
scheduler has the AI agent dial at the planned time, retries, skips blocked
numbers, and they show up in the callbacks list with their outcome.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from api.services.pbx.client import PbxError
from api.services.pbx.service import PbxRouteError, _connection, client_for

SOURCE = "pbx_missed"
SCOPES = ("queues", "all")
DEFAULT_POLICY: dict[str, Any] = {
    "enabled": False,
    "workflow_id": None,
    "delay_minutes": 5,
    "scope": "queues",
    "within_hours": True,
}


def read_policy(connection) -> dict[str, Any]:
    policy = {**DEFAULT_POLICY, **(connection.missed_call_policy or {})}
    if policy["scope"] not in SCOPES:
        policy["scope"] = "queues"
    return policy


async def save_policy(organization_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    from api.db import db_client

    connection = await _connection(organization_id)
    policy = {**read_policy(connection), **payload}
    if policy["scope"] not in SCOPES:
        raise PbxRouteError("Portée inconnue.", 422)
    delay = int(policy.get("delay_minutes") or 0)
    if not 0 <= delay <= 1440:
        raise PbxRouteError("Le délai va de 0 à 1 440 minutes.", 422)
    policy["delay_minutes"] = delay
    if policy["workflow_id"] is not None:
        workflow = await db_client.get_workflow(
            int(policy["workflow_id"]), organization_id=organization_id
        )
        if workflow is None:
            raise PbxRouteError("Agent IA introuvable.", 404)
        policy["workflow_id"] = workflow.id
    if policy["enabled"] and not policy["workflow_id"]:
        raise PbxRouteError("Choisissez l'agent IA qui rappellera les clients.", 422)
    await db_client.save_pbx_connection(organization_id, {"missed_call_policy": policy})
    return policy


async def recent_callbacks(
    organization_id: int, limit: int = 20
) -> list[dict[str, Any]]:
    from api.db import db_client

    rows = await db_client.list_callbacks_by_source(
        organization_id, SOURCE, limit=limit
    )
    return [
        {
            "id": c.id,
            "phone": c.phone,
            "customer_name": c.customer_name,
            "reason": c.reason,
            "status": c.status,
            "outcome": c.outcome,
            "attempts": c.attempts,
            "scheduled_at": c.scheduled_at.isoformat() if c.scheduled_at else None,
        }
        for c in rows
    ]


# ------------------------------------------------------------- call logs


def _external(cdr: dict[str, Any]) -> str | None:
    direction = (cdr.get("call_direction") or "").lower()
    if direction == "inbound":
        return cdr.get("source_extension")
    if direction == "outbound":
        return cdr.get("destination_extension") or cdr.get("requested_extension")
    return None


def _answered_by_a_person(cdr: dict[str, Any]) -> bool:
    return bool(cdr.get("answered")) and bool(
        cdr.get("destination_user_uuid") or cdr.get("source_user_uuid")
    )


async def _queue_numbers(connection) -> dict[str, str]:
    """Queue number → queue label, for the "queues only" policy."""
    try:
        async with client_for(connection) as client:
            queues = await client.queues()
    except PbxError:
        logger.opt(exception=True).warning("PBX queues unavailable for missed calls")
        return {}
    numbers = {}
    for queue in queues:
        for extension in queue.get("extensions") or []:
            if extension.get("exten"):
                numbers[str(extension["exten"])] = queue.get("label") or queue.get(
                    "name"
                )
    return numbers


async def _when(
    organization_id: int, policy: dict[str, Any], now: datetime
) -> datetime:
    at = now + timedelta(minutes=int(policy["delay_minutes"]))
    if not policy.get("within_hours"):
        return at
    try:
        from api.services.business.profile import get_business_profile, next_opening

        return next_opening(await get_business_profile(organization_id), at)
    except Exception:  # noqa: BLE001 - without a profile, the delay alone
        logger.opt(exception=True).debug("Business hours unavailable")
        return at


async def _timezone(organization_id: int) -> ZoneInfo:
    try:
        from api.services.business.profile import get_business_profile

        return ZoneInfo((await get_business_profile(organization_id)).timezone)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


async def _schedule(
    connection,
    policy,
    phone: str,
    *,
    reason: str,
    customer_name: str | None,
    now: datetime,
    handoff_id: str | None = None,
    notes: str | None = None,
):
    from api.services.contact_center.callbacks import create_or_update_callback
    from api.services.telephony.blocklist import find_block

    organization_id = connection.organization_id
    if await find_block(organization_id, phone, "outbound"):
        return None
    return await create_or_update_callback(
        organization_id,
        phone=phone,
        scheduled_at=await _when(organization_id, policy, now),
        source=SOURCE,
        assign_to="ai",
        reason=reason,
        customer_name=customer_name,
        workflow_id=policy["workflow_id"],
        handoff_id=handoff_id,
        notes=notes,
    )


async def on_call_log(
    connection, cdr: dict[str, Any], *, ai_routed: bool, now: datetime | None = None
) -> str | None:
    """React to one PBX call log. Returns what was done (for logs and tests)."""
    from api.db import db_client
    from api.services.customer_memory.service import normalize_phone
    from api.services.pbx import handoff

    now = now or datetime.now(UTC)
    organization_id = connection.organization_id
    phone = normalize_phone(_external(cdr))
    if not phone:
        return None
    policy = read_policy(connection)
    active = bool(policy["enabled"] and policy["workflow_id"])

    # 1. A caller the AI handed to a human: close the card.
    card = await handoff.card_for_caller(organization_id, phone, now)
    if card is not None:
        served = _answered_by_a_person(cdr)
        await db_client.update_call_handoff(
            organization_id,
            card.id,
            {"status": "answered", "answered_at": now}
            if served
            else {"status": "abandoned"},
        )
        if served:
            await _cancel_open_callbacks(organization_id, phone, now)
            return "handoff_answered"
        if active:
            await _schedule(
                connection,
                policy,
                phone,
                reason=card.reason
                or "Transféré par l'agent IA à l'équipe, mais personne n'a décroché",
                customer_name=card.customer_name,
                now=now,
                handoff_id=card.id,
                notes=card.summary,
            )
            return "handoff_abandoned_callback"
        return "handoff_abandoned"

    if ai_routed:
        return None  # the AI took the call itself

    # 2. A customer served: no callback for them any more.
    if cdr.get("answered"):
        cancelled = await _cancel_open_callbacks(organization_id, phone, now)
        return "served" if cancelled else None

    # 3. A missed inbound call.
    if (cdr.get("call_direction") or "").lower() != "inbound" or not active:
        return None
    target = str(
        cdr.get("requested_extension") or cdr.get("destination_extension") or ""
    )
    queue_label = None
    if policy["scope"] == "queues":
        queue_label = (await _queue_numbers(connection)).get(target)
        if not queue_label:
            return None
    tz = await _timezone(organization_id)
    when = now
    if cdr.get("start"):
        try:
            when = datetime.fromisoformat(str(cdr["start"]).replace("Z", "+00:00"))
        except ValueError:
            pass
    local = when.astimezone(tz) if when.tzinfo else when
    where = (
        f"la file {queue_label}"
        if queue_label
        else (cdr.get("destination_name") or cdr.get("requested_name") or "le standard")
    )
    await _schedule(
        connection,
        policy,
        phone,
        reason=f"Appel manqué le {local:%d/%m à %H:%M} ({where}) : rappeler le client "
        "et lui demander ce qu'il souhaitait.",
        customer_name=(cdr.get("source_name") or None),
        now=now,
    )
    return "missed_callback"


async def _cancel_open_callbacks(
    organization_id: int, phone: str, now: datetime
) -> int:
    from api.db import db_client

    callback = await db_client.find_open_callback_for_phone(organization_id, phone)
    if callback is None or callback.source != SOURCE or callback.status != "pending":
        return 0
    await db_client.update_callback_request(
        organization_id,
        callback.id,
        {
            "status": "canceled",
            "outcome": "Le client a été servi entre-temps : rappel annulé",
            "completed_at": now,
        },
    )
    return 1

"""Callbacks: never lose a caller.

Three ways in, one list:

* an AI agent's ``schedule_callback`` tool, when the customer would rather be
  called back (busy line, outside opening hours, "rappelez-moi demain") ;
* automatically, when a caller transferred to a contact-center queue is still
  unanswered after the queue's maximum wait (the AI handoff card becomes a
  callback with all its context) ;
* by hand, from the Centre d'appels page.

Two ways out:

* ``assign_to="ai"``: at the scheduled time the scheduler (arq cron, every
  minute) has the chosen AI agent place the call, with the reason in its
  context; failed attempts are retried every 15 minutes, up to
  ``max_attempts``;
* ``assign_to="human"``: the callback waits in the team's list; one click
  rings the agent's softphone and, when the agent answers, Asterisk dials the
  customer (server-side originate: agents still cannot dial out themselves).

One open callback per customer number: a new request updates it instead of
creating a duplicate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from api.services.customer_memory.service import normalize_phone

RETRY_DELAY = timedelta(minutes=15)
MAX_SCHEDULE_AHEAD = timedelta(days=30)
DEFAULT_MAX_ATTEMPTS = 3
ASAP_WORDS = {"", "asap", "now", "maintenant", "dès que possible", "des que possible"}
CALLBACK_DIALPLAN_CONTEXT = "nimbora-callback-out"


class CallbackError(ValueError):
    """A callback request that cannot be honored (bad number, missing agent…)."""


# ------------------------------------------------------------------- time


async def organization_timezone(organization_id: int) -> ZoneInfo:
    from api.services.organization_preferences import get_organization_preferences

    try:
        preferences = await get_organization_preferences(organization_id)
        if preferences.timezone:
            return ZoneInfo(preferences.timezone)
    except Exception:
        pass
    return ZoneInfo("UTC")


def parse_preferred_time(
    value: Any,
    *,
    now: datetime,
    tz: ZoneInfo,
    default_delay_minutes: int = 0,
) -> datetime:
    """When to call back. Naive times are the organization's local time.

    ``asap`` (or nothing) means now + the tool's default delay; past times
    become "now"; anything beyond 30 days is refused.
    """
    text = str(value or "").strip()
    if text.lower() in ASAP_WORDS:
        return now + timedelta(minutes=max(0, default_delay_minutes))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CallbackError(
            "preferred_time must be 'asap' or an ISO 8601 date/time "
            "such as 2026-11-21T10:00"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    parsed = parsed.astimezone(UTC)
    if parsed - now > MAX_SCHEDULE_AHEAD:
        raise CallbackError("A callback can be scheduled at most 30 days ahead")
    return max(parsed, now)


# ---------------------------------------------------------------- create


async def create_or_update_callback(
    organization_id: int,
    *,
    phone: Any,
    scheduled_at: datetime,
    source: str,
    assign_to: str = "human",
    reason: str | None = None,
    customer_name: str | None = None,
    queue_slug: str | None = None,
    workflow_id: int | None = None,
    origin_workflow_run_id: int | None = None,
    handoff_id: str | None = None,
    notes: str | None = None,
):
    from api.db import db_client

    normalized = normalize_phone(phone)
    if not normalized:
        raise CallbackError("A valid phone number is required for a callback")
    if assign_to not in {"human", "ai"}:
        raise CallbackError("assign_to must be 'human' or 'ai'")
    if assign_to == "ai" and not workflow_id:
        raise CallbackError("An AI callback needs the agent that will call")

    existing = await db_client.find_open_callback_for_phone(organization_id, normalized)
    if existing is not None and existing.status == "pending":
        merged_reason = reason or existing.reason
        if reason and existing.reason and reason not in existing.reason:
            merged_reason = f"{reason} (précédemment : {existing.reason})"
        return await db_client.update_callback_request(
            organization_id,
            existing.id,
            {
                "scheduled_at": min(existing.scheduled_at, scheduled_at)
                if existing.scheduled_at
                else scheduled_at,
                "reason": merged_reason,
                "customer_name": customer_name or existing.customer_name,
                "assign_to": assign_to,
                "queue_slug": queue_slug or existing.queue_slug,
                "workflow_id": workflow_id or existing.workflow_id,
            },
        )
    return await db_client.create_callback_request(
        organization_id=organization_id,
        phone=normalized,
        customer_name=(customer_name or None),
        reason=(reason or None),
        source=source,
        assign_to=assign_to,
        queue_slug=queue_slug,
        workflow_id=workflow_id,
        status="pending",
        scheduled_at=scheduled_at,
        attempts=0,
        max_attempts=DEFAULT_MAX_ATTEMPTS,
        origin_workflow_run_id=origin_workflow_run_id,
        handoff_id=handoff_id,
        notes=notes,
    )


async def schedule_callback_from_call(
    *,
    organization_id: int,
    workflow_run,
    gathered_context: dict[str, Any] | None,
    config: dict[str, Any],
    arguments: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Handler body of the ``schedule_callback`` tool. Returns the LLM result."""
    from api.services.customer_memory.service import customer_phone_from_context

    now = now or datetime.now(UTC)
    tz = await organization_timezone(organization_id)
    try:
        scheduled_at = parse_preferred_time(
            arguments.get("preferred_time"),
            now=now,
            tz=tz,
            default_delay_minutes=int(config.get("default_delay_minutes") or 0),
        )
        phone = arguments.get("phone_number") or customer_phone_from_context(
            dict(getattr(workflow_run, "initial_context", None) or {})
        )
        gathered = gathered_context or {}
        callback = await create_or_update_callback(
            organization_id,
            phone=phone,
            scheduled_at=scheduled_at,
            source="ai_agent",
            assign_to=config.get("assign_to") or "human",
            reason=str(arguments.get("reason") or "").strip()[:1000] or None,
            customer_name=(
                str(arguments.get("customer_name") or "").strip()[:128]
                or gathered.get("customer_name")
                or None
            ),
            queue_slug=config.get("queue_slug"),
            workflow_id=config.get("workflow_id"),
            origin_workflow_run_id=getattr(workflow_run, "id", None),
        )
    except CallbackError as exc:
        return {"status": "error", "error": str(exc)}
    local = callback.scheduled_at.astimezone(tz)
    return {
        "status": "scheduled",
        "callback_id": callback.id,
        "scheduled_for_local_time": local.strftime("%Y-%m-%d %H:%M"),
        "timezone": str(tz),
        "phone_number": callback.phone,
        "message": (
            "Callback scheduled. Confirm the date and time to the customer in "
            "their language, then close the conversation politely."
        ),
    }


# ------------------------------------------------------------- scheduler


async def convert_abandoned_handoffs(now: datetime | None = None) -> int:
    """Queue calls nobody answered in time become callbacks for the team."""
    from api.db import db_client

    now = now or datetime.now(UTC)
    converted = 0
    for handoff, _max_wait in await db_client.list_stale_pending_handoffs(now):
        try:
            if handoff.caller_number and normalize_phone(handoff.caller_number):
                await create_or_update_callback(
                    handoff.organization_id,
                    phone=handoff.caller_number,
                    scheduled_at=now,
                    source="queue_timeout",
                    assign_to="human",
                    reason=handoff.reason
                    or "Appel transféré à l'équipe mais resté sans réponse",
                    customer_name=handoff.customer_name,
                    queue_slug=handoff.queue_slug,
                    origin_workflow_run_id=handoff.workflow_run_id,
                    handoff_id=handoff.id,
                    notes=handoff.summary,
                )
                converted += 1
            await db_client.update_call_handoff(
                handoff.organization_id, handoff.id, {"status": "abandoned"}
            )
        except Exception:
            logger.opt(exception=True).warning(
                "Could not convert abandoned handoff {}", handoff.id
            )
    return converted


async def _place_ai_callback(callback) -> int:
    """Have the callback's AI agent dial the customer. Returns the run id."""
    from api.db import db_client
    from api.routes.public_agent import (
        ResolvedAgentTarget,
        TriggerCallRequest,
        _execute_resolved_target,
    )

    workflow = await db_client.get_workflow(
        callback.workflow_id, organization_id=callback.organization_id
    )
    if workflow is None:
        raise CallbackError("The AI agent assigned to this callback no longer exists")
    response = await _execute_resolved_target(
        ResolvedAgentTarget(
            workflow=workflow,
            organization_id=callback.organization_id,
            identifier_type="callback",
            identifier_value=str(callback.id),
        ),
        TriggerCallRequest(
            phone_number=callback.phone,
            initial_context={
                "callback_id": callback.id,
                "callback_reason": callback.reason or "",
                "customer_name": callback.customer_name or "",
                "callback_attempt": callback.attempts + 1,
            },
        ),
        use_draft=False,
        api_key_id=None,
        api_key_created_by=None,
    )
    return response.workflow_run_id


async def dispatch_due_ai_callbacks(now: datetime | None = None) -> int:
    """Place every due AI callback once (claim first: safe with many workers)."""
    from api.db import db_client

    now = now or datetime.now(UTC)
    placed = 0
    for callback in await db_client.list_due_ai_callbacks(now):
        claimed = await db_client.claim_callback_request(
            callback.organization_id,
            callback.id,
            fields={
                "status": "in_progress",
                "attempts": callback.attempts + 1,
                "last_attempt_at": now,
            },
        )
        if claimed is None:
            continue
        try:
            run_id = await _place_ai_callback(claimed)
            await db_client.update_callback_request(
                claimed.organization_id,
                claimed.id,
                {"callback_workflow_run_id": run_id},
            )
            placed += 1
        except Exception as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            await _retry_or_fail(claimed, f"Échec de l'appel : {detail}", now)
    return placed


async def _retry_or_fail(callback, outcome: str, now: datetime) -> None:
    from api.db import db_client

    if callback.attempts >= callback.max_attempts:
        await db_client.update_callback_request(
            callback.organization_id,
            callback.id,
            {"status": "failed", "outcome": outcome, "completed_at": now},
        )
    else:
        await db_client.update_callback_request(
            callback.organization_id,
            callback.id,
            {
                "status": "pending",
                "outcome": outcome,
                "scheduled_at": now + RETRY_DELAY,
            },
        )


async def complete_ai_callback_from_run(workflow_run, organization_id: int) -> None:
    """Post-call: close (or retry) the callback this AI call was placing."""
    from api.db import db_client

    try:
        callback = await db_client.get_callback_for_run(
            organization_id, workflow_run.id
        )
        if callback is None or callback.status != "in_progress":
            return
        now = datetime.now(UTC)
        duration = (workflow_run.usage_info or {}).get("call_duration_seconds") or 0
        if duration >= 5:
            disposition = (workflow_run.gathered_context or {}).get("call_disposition")
            await db_client.update_callback_request(
                organization_id,
                callback.id,
                {
                    "status": "done",
                    "completed_at": now,
                    "outcome": f"Rappelé par l'agent IA ({int(duration)} s)"
                    + (f" — {disposition}" if disposition else ""),
                },
            )
        else:
            await _retry_or_fail(callback, "Pas de réponse", now)
    except Exception:
        logger.opt(exception=True).warning("Could not close AI callback")


async def run_callback_scheduler(_ctx=None) -> dict[str, int]:
    """arq cron entry point: abandoned queue calls, then due AI callbacks."""
    now = datetime.now(UTC)
    converted = await convert_abandoned_handoffs(now)
    placed = await dispatch_due_ai_callbacks(now)
    if converted or placed:
        logger.info(
            "Callback scheduler: {} abandoned calls queued, {} AI callbacks placed",
            converted,
            placed,
        )
    return {"converted": converted, "placed": placed}


# ------------------------------------------------------- human click-to-call


async def dial_callback_for_agent(callback, agent) -> str:
    """Ring the agent's softphone, then dial the customer when they answer.

    Server-side ARI originate into a context that only this code can reach:
    agents keep no outbound dialing rights of their own.
    """
    import aiohttp

    from api.constants import (
        ASTERISK_ARI_PASSWORD,
        ASTERISK_ARI_URL,
        ASTERISK_ARI_USER,
    )

    if not ASTERISK_ARI_PASSWORD:
        raise CallbackError("The platform telephony (Asterisk) is not configured")
    label = (callback.customer_name or "Rappel").replace('"', "")[:40]
    params = {
        "endpoint": f"PJSIP/{agent.sip_username}",
        "extension": callback.phone,
        "context": CALLBACK_DIALPLAN_CONTEXT,
        "priority": 1,
        "callerId": f'"{label}" <{callback.phone}>',
        "timeout": 30,
    }
    body = {
        "variables": {
            "__NIMBORA_CALLBACK": str(callback.id),
            # Lets the softphone tell a callback from a queue call (no
            # handoff card).
            "PJSIP_HEADER(add,X-Nimbora-Callback)": str(callback.id),
        }
    }
    auth = aiohttp.BasicAuth(ASTERISK_ARI_USER, ASTERISK_ARI_PASSWORD)
    async with (
        aiohttp.ClientSession(
            auth=auth, timeout=aiohttp.ClientTimeout(total=10)
        ) as session,
        session.post(
            f"{ASTERISK_ARI_URL.rstrip('/')}/channels", params=params, json=body
        ) as response,
    ):
        text = await response.text()
        if response.status >= 300:
            raise CallbackError(f"Asterisk refused the call ({response.status})")
        import json

        return json.loads(text).get("id", "")

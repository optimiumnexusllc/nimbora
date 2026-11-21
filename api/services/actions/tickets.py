"""The ``create_ticket`` tool: open a support ticket, tell the caller its number,
and let callers follow up on their tickets.

* ``nimbora`` — built-in helpdesk (Activité → Tickets);
* ``zendesk`` / ``freshdesk`` — the ticket is created there; NIMBORA keeps a
  mirror row (number said to the caller, link to the external ticket) and
  asks the helpdesk for the live status on follow-up.

Callers only ever hear about tickets opened from their own number.
"""

from __future__ import annotations

from typing import Any

import httpx
from api.services.actions.common import (
    ActionContext,
    ActionError,
    basic_auth_pair,
    load_credential,
)

PRIORITIES = ("low", "normal", "high", "urgent")
STATUS_LABELS = {
    "open": "ouvert, en cours de traitement",
    "pending": "en attente d'une information",
    "solved": "résolu",
    "closed": "clôturé",
}
_FRESHDESK_PRIORITY = {"low": 1, "normal": 2, "high": 3, "urgent": 4}
_FRESHDESK_STATUS = {2: "open", 3: "pending", 4: "solved", 5: "closed"}
_ZENDESK_STATUS = {
    "new": "open",
    "open": "open",
    "pending": "pending",
    "hold": "pending",
    "solved": "solved",
    "closed": "closed",
}
TIMEOUT = httpx.Timeout(15.0)


def _description(args: dict[str, Any], ctx: ActionContext, phone: str | None) -> str:
    lines = [str(args.get("description") or "").strip()]
    if phone:
        lines.append(f"Téléphone de l'appelant : {phone}")
    if ctx.workflow_run_id:
        lines.append(f"Appel NIMBORA n° {ctx.workflow_run_id}")
    return "\n\n".join(line for line in lines if line)


async def _create_zendesk(config, credential, payload) -> tuple[str, str, str]:
    username, token = basic_auth_pair(*credential)
    domain = config["domain"]
    ticket: dict[str, Any] = {
        "subject": payload["subject"],
        "comment": {"body": payload["description"] or payload["subject"]},
        "priority": payload["priority"],
        "tags": ["nimbora"] + ([payload["category"]] if payload["category"] else []),
    }
    if payload.get("email"):
        ticket["requester"] = {
            "name": payload.get("name") or payload["email"],
            "email": payload["email"],
        }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"https://{domain}/api/v2/tickets.json",
            json={"ticket": ticket},
            auth=(username, token),
        )
    if response.status_code >= 300:
        raise ActionError(f"Zendesk refused the ticket ({response.status_code})")
    created = response.json()["ticket"]
    return str(created["id"]), f"https://{domain}/agent/tickets/{created['id']}", "open"


async def _create_freshdesk(config, credential, payload) -> tuple[str, str, str]:
    api_key, password = basic_auth_pair(*credential)
    domain = config["domain"]
    ticket: dict[str, Any] = {
        "subject": payload["subject"],
        "description": (payload["description"] or payload["subject"]).replace(
            "\n", "<br>"
        ),
        "priority": _FRESHDESK_PRIORITY[payload["priority"]],
        "status": 2,
        "tags": ["nimbora"] + ([payload["category"]] if payload["category"] else []),
    }
    if payload.get("email"):
        ticket["email"] = payload["email"]
    elif payload.get("phone"):
        ticket["phone"] = payload["phone"]
        ticket["name"] = payload.get("name") or payload["phone"]
    else:
        raise ActionError("Freshdesk needs the caller's e-mail or phone number")
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"https://{domain}/api/v2/tickets",
            json=ticket,
            auth=(api_key, password or "X"),
        )
    if response.status_code >= 300:
        raise ActionError(f"Freshdesk refused the ticket ({response.status_code})")
    created = response.json()
    return str(created["id"]), f"https://{domain}/a/tickets/{created['id']}", "open"


async def _external_status(config, credential, external_id: str) -> str | None:
    provider = config.get("provider")
    try:
        if provider == "zendesk":
            username, token = basic_auth_pair(*credential)
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(
                    f"https://{config['domain']}/api/v2/tickets/{external_id}.json",
                    auth=(username, token),
                )
            if response.status_code == 200:
                return _ZENDESK_STATUS.get(response.json()["ticket"]["status"])
        elif provider == "freshdesk":
            api_key, password = basic_auth_pair(*credential)
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(
                    f"https://{config['domain']}/api/v2/tickets/{external_id}",
                    auth=(api_key, password or "X"),
                )
            if response.status_code == 200:
                return _FRESHDESK_STATUS.get(response.json().get("status"))
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    return None


async def create(ctx: ActionContext, config: dict[str, Any], args: dict[str, Any]):
    from api.db import db_client
    from api.services.customer_memory.service import normalize_phone

    subject = str(args.get("subject") or "").strip()[:255]
    if not subject:
        raise ActionError("subject is required: summarize the request in a few words")
    priority = str(args.get("priority") or config.get("default_priority") or "normal")
    if priority not in PRIORITIES:
        priority = "normal"
    categories = config.get("categories") or []
    category = str(args.get("category") or "").strip()[:64] or None
    if categories and category not in categories:
        category = None
    phone = normalize_phone(args.get("phone")) or ctx.caller_phone
    payload = {
        "subject": subject,
        "description": _description(args, ctx, phone),
        "priority": priority,
        "category": category,
        "name": str(args.get("name") or ctx.customer_name or "").strip()[:128] or None,
        "email": str(args.get("email") or "").strip()[:255] or None,
        "phone": phone,
    }
    provider = config.get("provider") or "nimbora"
    external_id = external_url = None
    if provider in {"zendesk", "freshdesk"}:
        credential = await load_credential(
            ctx.organization_id, config.get("credential_uuid")
        )
        creator = _create_zendesk if provider == "zendesk" else _create_freshdesk
        try:
            external_id, external_url, _ = await creator(config, credential, payload)
        except httpx.HTTPError as exc:
            raise ActionError(f"{provider} could not be reached") from exc
    ticket = await db_client.create_ticket(
        organization_id=ctx.organization_id,
        provider=provider,
        external_id=external_id,
        external_url=external_url,
        subject=subject,
        description=payload["description"],
        category=category,
        priority=priority,
        status="open",
        customer_name=payload["name"],
        phone=phone,
        email=payload["email"],
        workflow_run_id=ctx.workflow_run_id,
    )
    return {
        "status": "created",
        "ticket_number": ticket.number,
        "message": (
            "Give the caller the ticket number digit by digit and tell them the "
            "team will follow up."
        ),
    }


async def lookup(ctx: ActionContext, config: dict[str, Any], args: dict[str, Any]):
    from api.db import db_client

    if config.get("allow_lookup") is False:
        return {
            "status": "not_allowed",
            "message": "Ticket follow-up is not handled by phone.",
        }
    phone = ctx.caller_phone
    if not phone:
        return {
            "status": "unknown_caller",
            "message": "The caller's number is unknown.",
        }
    tickets = []
    if args.get("ticket_number"):
        try:
            number = int(str(args["ticket_number"]).strip().lstrip("#"))
        except ValueError as exc:
            raise ActionError("ticket_number must be a number") from exc
        ticket = await db_client.get_ticket_by_number(ctx.organization_id, number)
        if ticket is not None and ticket.phone == phone:
            tickets = [ticket]
    else:
        tickets = (await db_client.list_tickets(ctx.organization_id, phone=phone))[:3]
    if not tickets:
        return {"status": "not_found", "message": "No ticket found for this caller."}
    credential = None
    if config.get("provider") in {"zendesk", "freshdesk"}:
        try:
            credential = await load_credential(
                ctx.organization_id, config.get("credential_uuid")
            )
        except ActionError:
            credential = None
    results = []
    for ticket in tickets:
        status = ticket.status
        if (
            credential
            and ticket.external_id
            and ticket.provider == config.get("provider")
        ):
            live = await _external_status(config, credential, ticket.external_id)
            if live and live != status:
                status = live
                await db_client.update_ticket(
                    ctx.organization_id, ticket.id, {"status": live}
                )
        results.append(
            {
                "ticket_number": ticket.number,
                "subject": ticket.subject,
                "status": status,
                "status_label": STATUS_LABELS.get(status, status),
                "resolution": ticket.resolution
                if status in {"solved", "closed"}
                else None,
            }
        )
    return {"status": "ok", "tickets": results}


async def handle_ticket(
    ctx: ActionContext, config: dict[str, Any], args: dict[str, Any]
):
    action = str(args.get("action") or "create")
    if action == "lookup":
        return await lookup(ctx, config, args)
    if action == "create":
        return await create(ctx, config, args)
    raise ActionError(f"Unknown action '{action}'")

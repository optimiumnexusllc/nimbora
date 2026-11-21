"""Enterprise PBX: connection, inventory, AI routing, white-label, events.

The PBX engine (Wazo Platform) is shown to users only under the platform brand
(``services.branding``). Calls for AI agents go through the PBX's Asterisk with
the organization's ARI configuration: a PBX number is routed with a custom
destination ``Stasis(<app>,inbound,called=<number>)``, and NIMBORA picks the
agent from that number like for any ARI inbound call.
"""

from __future__ import annotations

import asyncio
import re
import secrets
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.services.branding import brand
from api.services.pbx.client import PbxClient, PbxError, PbxSettings

WEBHOOK_EVENTS = ["call_log_created", "agent_status_update"]
ROUTE_METADATA_KEY = "pbx_route"
DEDUP_TTL_SECONDS = 7 * 24 * 3600
_NUMBER = re.compile(r"^\+?[0-9]{2,20}$")


class PbxNotConfigured(Exception):
    pass


class PbxRouteError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def new_webhook_token() -> str:
    return secrets.token_urlsafe(32)


def assert_pbx_url_allowed(url: str) -> None:
    """SSRF guard (SaaS): same rule as HTTP tools, except the operator's PBXs."""
    from urllib.parse import urlparse

    from api.constants import PBX_ALLOWED_HOSTS
    from api.utils.url_security import validate_user_configured_service_url

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("L'adresse du PBX doit commencer par https:// (ou http://)")
    if parsed.hostname.lower() in {h.lower() for h in PBX_ALLOWED_HOSTS}:
        return
    try:
        validate_user_configured_service_url(url, field_name="Adresse du PBX")
    except ValueError as error:
        raise ValueError(
            "Cette adresse de PBX n'est pas joignable publiquement. S'il s'agit du "
            "PBX de l'opérateur sur le réseau interne, ajoutez son nom à "
            "PBX_ALLOWED_HOSTS."
        ) from error


def settings_for(connection) -> PbxSettings:
    return PbxSettings(
        base_url=connection.base_url,
        username=connection.username,
        password=connection.password,
        tenant_uuid=connection.tenant_uuid or None,
        verify_tls=bool(connection.verify_tls),
    )


def client_for(connection, **kwargs) -> PbxClient:
    return PbxClient(settings_for(connection), **kwargs)


async def _connection(organization_id: int):
    from api.db import db_client

    connection = await db_client.get_pbx_connection(organization_id)
    if connection is None:
        raise PbxNotConfigured()
    # Re-checked on every use: DNS may change after the connection was saved.
    try:
        assert_pbx_url_allowed(connection.base_url)
    except ValueError as error:
        raise PbxError(str(error)) from error
    return connection


# ------------------------------------------------------------- status


async def probe(settings: PbxSettings, **client_kwargs) -> dict[str, Any]:
    """Credentials, engine version and tenant, in one pass."""
    async with PbxClient(settings, **client_kwargs) as client:
        await client.token(refresh=True)
        infos = await client.infos()
        tenant_name = None
        if settings.tenant_uuid:
            tenant = await client.check_tenant(settings.tenant_uuid)
            tenant_name = (tenant or {}).get("name")
        return {
            "engine_version": (infos or {}).get("wazo_version"),
            "engine_uuid": (infos or {}).get("uuid"),
            "tenant_name": tenant_name,
        }


async def refresh_status(organization_id: int, **client_kwargs) -> Any:
    """Probe the PBX and store the result on the connection."""
    from api.db import db_client

    connection = await _connection(organization_id)
    fields: dict[str, Any] = {"last_checked_at": datetime.now(UTC)}
    try:
        result = await probe(settings_for(connection), **client_kwargs)
        fields.update(
            status="ok",
            last_error=None,
            engine_version=(result.get("engine_version") or None),
        )
    except PbxError as error:
        fields.update(status="error", last_error=str(error)[:500])
    return await db_client.save_pbx_connection(organization_id, fields)


# ---------------------------------------------------------- inventory


def _routed_numbers(phone_rows) -> dict[str, Any]:
    return {
        row.address_normalized: row
        for row in phone_rows
        if (row.extra_metadata or {}).get(ROUTE_METADATA_KEY)
    }


async def _ai_phone_rows(connection) -> list:
    from api.db import db_client

    if not connection.ari_configuration_id:
        return []
    return await db_client.list_phone_numbers_for_config(
        connection.ari_configuration_id
    )


def _incall_numbers(incall: dict) -> list[str]:
    return [e.get("exten") for e in incall.get("extensions") or [] if e.get("exten")]


def _describe_destination(destination: dict | None) -> str:
    destination = destination or {}
    kind = destination.get("type")
    labels = {
        "user": "Poste",
        "group": "Groupe",
        "queue": "File d'attente",
        "voicemail": "Messagerie",
        "ivr": "Serveur vocal",
        "conference": "Conférence",
        "extension": "Extension",
        "hangup": "Raccrocher",
        "sound": "Message",
        "switchboard": "Standard",
        "application": "Application",
        "custom": "Personnalisée",
        "none": "Aucune",
    }
    return labels.get(kind or "", kind or "—")


def _destination_target(destination: dict | None) -> int | None:
    destination = destination or {}
    for key in (
        "queue_id",
        "user_id",
        "voicemail_id",
        "ivr_id",
        "group_id",
        "conference_id",
    ):
        if destination.get(key) is not None:
            return destination[key]
    return None


async def inventory(organization_id: int, **client_kwargs) -> dict[str, Any]:
    """Everything the PBX page shows. Each section fails on its own."""
    from api.db import db_client

    connection = await _connection(organization_id)
    phone_rows = await _ai_phone_rows(connection)
    routed = _routed_numbers(phone_rows)
    workflows = {}
    for row in routed.values():
        if row.inbound_workflow_id and row.inbound_workflow_id not in workflows:
            workflow = await db_client.get_workflow(
                row.inbound_workflow_id, organization_id=organization_id
            )
            workflows[row.inbound_workflow_id] = workflow.name if workflow else None

    result: dict[str, Any] = {"errors": {}}
    async with client_for(connection, **client_kwargs) as client:

        async def section(name: str, coro):
            try:
                result[name] = await coro
            except PbxError as error:
                result[name] = []
                result["errors"][name] = str(error)

        await asyncio.gather(
            section("users", client.users()),
            section("queues", client.queues()),
            section("agents", client.agents()),
            section("agent_statuses", client.agent_statuses()),
            section("incalls", client.incalls()),
            section("calls", client.calls()),
        )

    statuses = {s.get("id"): s for s in result.pop("agent_statuses") or []}
    overflows = {}
    for row in phone_rows:
        meta = (row.extra_metadata or {}).get("pbx_overflow")
        if meta and row.is_active and row.inbound_workflow_id:
            if row.inbound_workflow_id not in workflows:
                workflow = await db_client.get_workflow(
                    row.inbound_workflow_id, organization_id=organization_id
                )
                workflows[row.inbound_workflow_id] = workflow.name if workflow else None
            overflows[meta.get("queue_id")] = {
                "workflow_id": row.inbound_workflow_id,
                "workflow_name": workflows.get(row.inbound_workflow_id),
            }
    users = [
        {
            "id": u.get("id"),
            "uuid": u.get("uuid"),
            "name": " ".join(
                p for p in (u.get("firstname"), u.get("lastname")) if p
            ).strip()
            or u.get("email")
            or "—",
            "extension": u.get("extension"),
            "email": u.get("email"),
            "login": u.get("username") or u.get("email"),
            "enabled": u.get("enabled", True),
        }
        for u in result["users"]
    ]
    queues = [
        {
            "overflow": overflows.get(q.get("id")),
            "wait_time_threshold": q.get("wait_time_threshold"),
            "agent_ids": [
                a.get("id") for a in (q.get("members") or {}).get("agents") or []
            ],
            "id": q.get("id"),
            "name": q.get("label") or q.get("name"),
            "extensions": [e.get("exten") for e in q.get("extensions") or []],
            "members": len((q.get("members") or {}).get("agents") or [])
            + len((q.get("members") or {}).get("users") or []),
        }
        for q in result["queues"]
    ]
    agents = []
    for agent in result["agents"]:
        status = statuses.get(agent.get("id")) or {}
        agents.append(
            {
                "id": agent.get("id"),
                "number": agent.get("number"),
                "name": " ".join(
                    p for p in (agent.get("firstname"), agent.get("lastname")) if p
                ).strip()
                or f"Agent {agent.get('number')}",
                "logged": bool(status.get("logged")),
                "paused": bool(status.get("paused")),
                "paused_reason": status.get("paused_reason"),
                "extension": status.get("extension"),
            }
        )
    numbers = []
    from api.services.customer_memory.service import normalize_phone

    for incall in result["incalls"]:
        for exten in _incall_numbers(incall):
            row = routed.get(normalize_phone(exten) or exten) or routed.get(exten)
            ai = bool(
                row
                and (row.extra_metadata or {})
                .get(ROUTE_METADATA_KEY, {})
                .get("incall_id")
                == incall.get("id")
            )
            numbers.append(
                {
                    "schedules": [
                        sc.get("name") for sc in incall.get("schedules") or []
                    ],
                    "number": exten,
                    "incall_id": incall.get("id"),
                    "description": incall.get("description"),
                    "destination": "Agent IA"
                    if ai
                    else _describe_destination(incall.get("destination")),
                    "destination_type": "ai"
                    if ai
                    else (incall.get("destination") or {}).get("type"),
                    "destination_target_id": _destination_target(
                        incall.get("destination")
                    ),
                    "ai_workflow_id": row.inbound_workflow_id if ai else None,
                    "ai_workflow_name": workflows.get(row.inbound_workflow_id)
                    if ai
                    else None,
                }
            )
    calls = [
        {
            "call_id": c.get("call_id"),
            "caller": c.get("caller_id_number"),
            "caller_name": c.get("caller_id_name"),
            "peer": c.get("peer_caller_id_number"),
            "peer_name": c.get("peer_caller_id_name"),
            "status": c.get("status"),
            "direction": c.get("direction"),
            "since": c.get("answer_time") or c.get("creation_time"),
            "on_hold": bool(c.get("on_hold")),
        }
        for c in result["calls"]
    ]
    return {
        "users": users,
        "queues": queues,
        "agents": agents,
        "numbers": numbers,
        "calls": calls,
        "errors": result["errors"],
    }


# ---------------------------------------------------------- AI routing


async def _incall_context(client: PbxClient, connection) -> str:
    if connection.incall_context:
        return connection.incall_context
    contexts = await client.contexts("incall")
    if not contexts:
        raise PbxRouteError(
            "Aucun contexte d'appels entrants sur le PBX : créez-en un ou "
            "indiquez-le dans la connexion.",
            409,
        )
    return contexts[0]["name"]


async def route_number_to_agent(
    organization_id: int,
    number: str,
    workflow_id: int,
    **client_kwargs,
) -> dict[str, Any]:
    """Make a PBX number ring an AI agent (created on the PBX and in NIMBORA)."""
    from api.db import db_client
    from api.services.customer_memory.service import normalize_phone

    number = number.strip().replace(" ", "")
    if not _NUMBER.match(number):
        raise PbxRouteError("Numéro invalide")
    connection = await _connection(organization_id)
    if not connection.ari_configuration_id:
        raise PbxRouteError(
            "Reliez d'abord une configuration ARI (l'accès des agents IA au PBX).",
            409,
        )
    ari = await db_client.get_telephony_configuration_for_org(
        connection.ari_configuration_id, organization_id
    )
    if ari is None or ari.provider != "ari":
        raise PbxRouteError("Configuration ARI introuvable", 404)
    stasis_app = (ari.credentials or {}).get("stasis_app_name") or (
        ari.credentials or {}
    ).get("app_name")
    workflow = await db_client.get_workflow(
        workflow_id, organization_id=organization_id
    )
    if workflow is None:
        raise PbxRouteError("Agent introuvable", 404)

    async with client_for(connection, **client_kwargs) as client:
        context = await _incall_context(client, connection)
        existing = await client.extensions(exten=number, context=context)
        if existing:
            raise PbxRouteError(
                f"Le numéro {number} a déjà une destination sur le PBX : "
                "retirez-la d'abord pour éviter de couper un routage existant.",
                409,
            )
        extension = await client.create_extension(number, context)
        try:
            incall = await client.create_incall(
                {
                    "type": "custom",
                    "command": f"Stasis({stasis_app},inbound,called={number})",
                },
                f"{brand().name} — agent IA « {workflow.name} »"[:255],
            )
            await client.associate_incall_extension(incall["id"], extension["id"])
        except PbxError:
            await client.delete_extension(extension["id"])
            raise

    metadata = {
        ROUTE_METADATA_KEY: {
            "incall_id": incall["id"],
            "extension_id": extension["id"],
            "context": context,
        }
    }
    normalized = normalize_phone(number) or number
    rows = await db_client.list_phone_numbers_for_config(ari.id)
    row = next((r for r in rows if r.address_normalized == normalized), None)
    if row is None:
        row = await db_client.create_phone_number(
            organization_id=organization_id,
            telephony_configuration_id=ari.id,
            address=number,
            label=f"PBX {number}",
            inbound_workflow_id=workflow.id,
            extra_metadata=metadata,
        )
    else:
        row = await db_client.update_phone_number(
            row.id,
            ari.id,
            inbound_workflow_id=workflow.id,
            is_active=True,
            extra_metadata={**(row.extra_metadata or {}), **metadata},
        )
    return {
        "number": number,
        "incall_id": incall["id"],
        "workflow_id": workflow.id,
        "workflow_name": workflow.name,
        "phone_number_id": row.id,
    }


async def unroute_number(organization_id: int, number: str, **client_kwargs) -> bool:
    from api.db import db_client
    from api.services.customer_memory.service import normalize_phone

    connection = await _connection(organization_id)
    rows = await _ai_phone_rows(connection)
    normalized = normalize_phone(number) or number
    row = next(
        (
            r
            for r in rows
            if r.address_normalized == normalized
            and (r.extra_metadata or {}).get(ROUTE_METADATA_KEY)
        ),
        None,
    )
    if row is None:
        return False
    route = row.extra_metadata[ROUTE_METADATA_KEY]
    async with client_for(connection, **client_kwargs) as client:
        if route.get("adopted"):
            # The number existed before the AI took it: give it back its
            # previous destination instead of deleting it.
            try:
                current = await client.incall(route["incall_id"])
                body = {
                    k: v
                    for k, v in (current or {}).items()
                    if k
                    in {
                        "preprocess_subroutine",
                        "greeting_sound",
                        "caller_id_mode",
                        "caller_id_name",
                        "description",
                    }
                }
                body["destination"] = route.get("previous_destination") or {
                    "type": "none"
                }
                await client.update_incall(route["incall_id"], body)
            except PbxError as error:
                if error.status != 404:
                    raise
        for action, ident in (
            (
                client.delete_incall,
                None if route.get("adopted") else route.get("incall_id"),
            ),
            (client.delete_extension, route.get("extension_id")),
        ):
            if ident is None:
                continue
            try:
                await action(ident)
            except PbxError as error:
                if error.status != 404:  # already gone on the PBX: fine
                    raise
    metadata = {
        k: v for k, v in (row.extra_metadata or {}).items() if k != ROUTE_METADATA_KEY
    }
    await db_client.update_phone_number(
        row.id,
        row.telephony_configuration_id,
        is_active=False,
        extra_metadata=metadata,
        clear_inbound_workflow=True,
    )
    return True


# ---------------------------------------------------------- white label


async def apply_branding(organization_id: int, **client_kwargs) -> dict[str, str]:
    """Rebrand what the PBX exposes through its API (SIP User-Agent/Server)."""
    from api.db import db_client

    connection = await _connection(organization_id)
    user_agent = brand().sip_user_agent
    async with client_for(connection, **client_kwargs) as client:
        options = await client.pjsip_global()
        options["user_agent"] = user_agent
        await client.set_pjsip_global(options)
    await db_client.save_pbx_connection(
        organization_id, {"branding_applied_at": datetime.now(UTC)}
    )
    return {"sip_user_agent": user_agent}


# -------------------------------------------------------------- events


def webhook_url(public_base_url: str, token: str) -> str:
    # {{ event_name }} is filled in by the PBX's webhook templates.
    return (
        f"{public_base_url.rstrip('/')}/api/v1/pbx/events/{token}"
        "?event={{ event_name }}"
    )


async def ensure_webhook(
    organization_id: int, public_base_url: str, **client_kwargs
) -> str:
    """(Re)create the PBX subscription that sends call events to NIMBORA."""
    from api.db import db_client

    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        if connection.webhook_subscription_uuid:
            try:
                await client.delete_subscription(connection.webhook_subscription_uuid)
            except PbxError as error:
                if error.status != 404:
                    raise
        subscription = await client.create_subscription(
            {
                "name": f"{brand().name} — événements"[:128],
                "service": "http",
                "events": WEBHOOK_EVENTS,
                "config": {
                    "url": webhook_url(public_base_url, connection.webhook_token),
                    "method": "post",
                    "content_type": "application/json",
                    "verify_certificate": "true",
                },
            }
        )
    await db_client.save_pbx_connection(
        organization_id, {"webhook_subscription_uuid": subscription.get("uuid")}
    )
    return subscription.get("uuid")


def _human_call_interaction(cdr: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """(customer phone, interaction fields) for a PBX call log."""
    from api.services.customer_memory.service import normalize_phone

    direction = (cdr.get("call_direction") or cdr.get("call_drection") or "").lower()
    if direction == "inbound":
        external = cdr.get("source_extension")
        staff = cdr.get("destination_name") or cdr.get("requested_name")
    elif direction == "outbound":
        external = cdr.get("destination_extension") or cdr.get("requested_extension")
        staff = cdr.get("source_name")
    else:
        return None, {}  # internal call: no customer
    phone = normalize_phone(external)
    if not phone or len(re.sub(r"\D", "", phone)) < 6:
        return None, {}
    answered = bool(cdr.get("answered"))
    duration = int(float(cdr.get("duration") or 0))
    minutes = max(1, round(duration / 60)) if duration else 0
    if not answered:
        summary = "Appel manqué" if direction == "inbound" else "Appel sans réponse"
    else:
        sense = "entrant" if direction == "inbound" else "sortant"
        summary = f"Appel {sense} avec {staff or 'un conseiller'}"
        if minutes:
            summary += f" ({minutes} min)"
    return phone, {
        "direction": direction,
        "agent_name": (staff or None) and str(staff)[:255],
        "summary": summary,
        "outcome": "answered" if answered else "missed",
        "duration_seconds": duration or None,
        "channel": "phone",
    }


async def handle_event(connection, event_name: str | None, payload: Any) -> str:
    """Process one webhook delivery; returns what was done (for logs/tests)."""
    from api.db import db_client
    from api.services.customer_memory.service import (
        is_memory_enabled,
        normalize_phone,
        phone_suffix,
    )
    from api.services.supervision.live_calls import get_redis

    data = (
        payload.get("data")
        if isinstance(payload, dict) and "data" in payload
        else payload
    )
    name = event_name or (payload.get("name") if isinstance(payload, dict) else None)
    if name != "call_log_created" or not isinstance(data, dict):
        return "ignored"

    redis = await get_redis()
    key = f"nimbora:pbx:cdr:{connection.organization_id}:{data.get('id')}"
    if data.get("id") is not None and not await redis.set(
        key, "1", nx=True, ex=DEDUP_TTL_SECONDS
    ):
        return "duplicate"

    phone, fields = _human_call_interaction(data)
    if not phone:
        return "no_customer"
    # Calls NIMBORA's own agents took are recorded by the agent run itself.
    routed = _routed_numbers(await _ai_phone_rows(connection))
    for number in (data.get("requested_extension"), data.get("destination_extension")):
        if number and (normalize_phone(number) or number) in routed:
            return "ai_call"
    if not await is_memory_enabled(connection.organization_id):
        return "memory_off"
    profile = await db_client.get_or_create_customer_profile(
        connection.organization_id, phone, phone_suffix(phone)
    )
    await db_client.record_customer_interaction(
        connection.organization_id, profile.id, workflow_run_id=None, fields=fields
    )
    if not profile.last_summary or fields["outcome"] == "answered":
        await db_client.update_customer_profile(
            connection.organization_id,
            profile.id,
            {"last_summary": fields["summary"]},
        )
    logger.info(
        f"[PBX org={connection.organization_id}] Human call recorded for customer {profile.id}"
    )
    return "recorded"


# ------------------------------------------------------- password reset


async def reset_user_password(
    host: str, user_uuid: str, email_token: str, password: str, **client_kwargs
) -> None:
    """Finish a PBX password reset started from the white-label e-mail.

    The host comes from the e-mail link, so it is only used to pick one of the
    PBXs NIMBORA already knows (never to reach an arbitrary address).
    """
    from urllib.parse import urlparse

    from api.db import db_client

    wanted = (host or "").strip().lower()
    for connection in await db_client.list_pbx_connections():
        parsed = urlparse(connection.base_url)
        candidates = {parsed.netloc.lower(), (parsed.hostname or "").lower()}
        if wanted and wanted in candidates:
            async with client_for(connection, **client_kwargs) as client:
                await client.reset_password_with_email_token(
                    user_uuid, email_token, password
                )
            return
    raise PbxNotConfigured()

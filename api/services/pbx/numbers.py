"""Public numbers (DIDs) of the PBX and where each one rings: a queue, a
person, a voicemail, a voice menu, an AI agent — or nowhere.
"""

from __future__ import annotations

from typing import Any

from api.services.branding import brand
from api.services.pbx.client import PbxClient, PbxError
from api.services.pbx.ivr import MenuAction
from api.services.pbx.service import (
    _NUMBER,
    ROUTE_METADATA_KEY,
    PbxRouteError,
    _ai_phone_rows,
    _connection,
    _incall_context,
    client_for,
    route_number_to_agent,
)

INCALL_EDITABLE = {
    "preprocess_subroutine",
    "greeting_sound",
    "caller_id_mode",
    "caller_id_name",
    "description",
    "destination",
}


def _clean(number: str) -> str:
    number = (number or "").strip().replace(" ", "")
    if not _NUMBER.match(number):
        raise PbxRouteError("Numéro invalide", 422)
    return number


async def _find_incall(client: PbxClient, number: str) -> dict | None:
    for incall in await client.incalls():
        if any(e.get("exten") == number for e in incall.get("extensions") or []):
            return incall
    return None


async def _ai_row(connection, incall_id: int):
    for row in await _ai_phone_rows(connection):
        route = (row.extra_metadata or {}).get(ROUTE_METADATA_KEY) or {}
        if route.get("incall_id") == incall_id:
            return row
    return None


async def _pbx_destination(organization_id: int, action: MenuAction) -> dict:
    from api.db import db_client

    if action.type == "queue":
        return {"type": "queue", "queue_id": action.target_id}
    if action.type == "group":
        return {"type": "group", "group_id": action.target_id}
    if action.type == "conference":
        return {"type": "conference", "conference_id": action.target_id}
    if action.type == "user":
        return {"type": "user", "user_id": action.target_id}
    if action.type == "voicemail":
        return {"type": "voicemail", "voicemail_id": action.target_id}
    if action.type == "menu":
        menu = await db_client.get_pbx_ivr_menu(action.target_id, organization_id)
        if menu is None:
            raise PbxRouteError("Menu introuvable", 404)
        if not menu.pbx_ivr_id:
            raise PbxRouteError(f"Publiez d'abord le menu « {menu.name} ».", 409)
        return {"type": "ivr", "ivr_id": menu.pbx_ivr_id}
    return {"type": "hangup", "cause": "normal"}


async def _set_incall_destination(
    client: PbxClient, incall: dict, destination: dict, description: str | None = None
) -> None:
    current = await client.incall(incall["id"])
    body = {k: v for k, v in (current or {}).items() if k in INCALL_EDITABLE}
    body["destination"] = destination
    if description is not None:
        body["description"] = description
    await client.update_incall(incall["id"], body)


async def _release_ai(row) -> None:
    """The number no longer goes to an AI agent: forget the route."""
    from api.db import db_client

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


async def set_number_destination(
    organization_id: int, number: str, action: MenuAction, **client_kwargs
) -> dict[str, Any]:
    """Point a public number at a destination, creating it on the PBX if new.

    Existing numbers keep their settings (schedules, caller ID); only the
    destination changes. Switching to or from an AI agent keeps NIMBORA's
    inbound routing in step.
    """
    from api.db import db_client

    number = _clean(number)
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        incall = await _find_incall(client, number)
    if action.type == "ai":
        workflow = await db_client.get_workflow(
            action.target_id, organization_id=organization_id
        )
        if workflow is None:
            raise PbxRouteError("Agent introuvable", 404)
        if incall is None:
            return await route_number_to_agent(
                organization_id, number, workflow.id, **client_kwargs
            )
        return await _adopt_for_ai(
            organization_id, connection, number, incall, workflow, **client_kwargs
        )

    destination = await _pbx_destination(organization_id, action)
    async with client_for(connection, **client_kwargs) as client:
        if incall is None:
            context = await _incall_context(client, connection)
            extension = await client.create_extension(number, context)
            try:
                incall = await client.create_incall(
                    destination, f"{brand().name} — {number}"
                )
                await client.associate_incall_extension(incall["id"], extension["id"])
            except PbxError:
                await client.delete_extension(extension["id"])
                raise
        else:
            await _set_incall_destination(client, incall, destination)
    row = await _ai_row(connection, incall["id"])
    if row is not None:
        await _release_ai(row)
    return {"number": number, "incall_id": incall["id"], "destination": action.type}


async def _adopt_for_ai(
    organization_id: int,
    connection,
    number: str,
    incall: dict,
    workflow,
    **client_kwargs,
) -> dict[str, Any]:
    """An existing PBX number now rings an AI agent (its incall is kept)."""
    from api.db import db_client
    from api.services.customer_memory.service import normalize_phone

    if not connection.ari_configuration_id:
        raise PbxRouteError(
            "Reliez d'abord une configuration ARI (l'accès des agents IA au PBX).", 409
        )
    ari = await db_client.get_telephony_configuration_for_org(
        connection.ari_configuration_id, organization_id
    )
    if ari is None or ari.provider != "ari":
        raise PbxRouteError("Configuration ARI introuvable", 404)
    stasis_app = (ari.credentials or {}).get("stasis_app_name") or (
        ari.credentials or {}
    ).get("app_name")
    previous = incall.get("destination") or {}
    async with client_for(connection, **client_kwargs) as client:
        await _set_incall_destination(
            client,
            incall,
            {
                "type": "custom",
                "command": f"Stasis({stasis_app},inbound,called={number})",
            },
        )
    existing = await _ai_row(connection, incall["id"])
    route = (
        (existing.extra_metadata or {}).get(ROUTE_METADATA_KEY) if existing else None
    )
    metadata = {
        ROUTE_METADATA_KEY: route
        or {
            "incall_id": incall["id"],
            "extension_id": None,  # the number existed before: never deleted
            "adopted": True,
            "previous_destination": previous,
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


async def remove_number(organization_id: int, number: str, **client_kwargs) -> bool:
    """Take a number off the PBX (its incall and, if ours, its extension)."""
    number = _clean(number)
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        incall = await _find_incall(client, number)
        if incall is None:
            return False
        await client.delete_incall(incall["id"])
        for extension in incall.get("extensions") or []:
            if extension.get("exten") == number and extension.get("id"):
                try:
                    await client.delete_extension(extension["id"])
                except PbxError as error:
                    if error.status != 404:
                        raise
    row = await _ai_row(connection, incall["id"])
    if row is not None:
        await _release_ai(row)
    return True

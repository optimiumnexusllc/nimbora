"""Call groups ("groupes d'appel") of the enterprise PBX.

A group rings several extensions behind one internal number — all at once,
in turn, or to whoever has been idle the longest. When nobody answers, the
call goes on to a fallback: a voicemail, a queue, another extension, a voice
menu, or an AI agent.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from api.services.pbx.admin import (
    AI_KEY_PREFIX,
    EXTEN,
    _ai_destination,
    _clear_ai_destination,
    _internal_context,
)
from api.services.pbx.client import PbxClient, PbxError
from api.services.pbx.ivr import MenuAction
from api.services.pbx.numbers import _pbx_destination
from api.services.pbx.service import PbxRouteError, _connection, client_for

GROUP_METADATA_KEY = "pbx_group"
RING_STRATEGIES = {
    "all": "Tous les postes en même temps",
    "linear": "Dans l'ordre de la liste",
    "memorized_round_robin": "Chacun son tour",
    "least_recent": "Le poste libre depuis le plus longtemps",
    "fewest_calls": "Le poste qui a pris le moins d'appels",
    "random": "Au hasard",
}
_LABEL = re.compile(r"[^-_.a-zA-Z0-9 ]+")


def ascii_label(label: str) -> str:
    """The PBX accepts only ASCII letters, digits, spaces and ``-_.`` here."""
    text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", _LABEL.sub(" ", text)).strip()[:128]


def group_key(group_id: int) -> str:
    return f"{AI_KEY_PREFIX}g{group_id}"


async def fallback_destination(
    organization_id: int,
    connection,
    action: MenuAction | None,
    *,
    key: str,
    metadata_key: str,
    meta: dict,
) -> dict | None:
    """A PBX destination for ``action``; ``None`` leaves the call unrouted."""
    if action is None:
        return None
    if action.type == "ai":
        return await _ai_destination(
            organization_id, connection, key, action.target_id, metadata_key, meta
        )
    return await _pbx_destination(organization_id, action)


@dataclass
class NewGroup:
    label: str
    extension: str
    strategy: str = "all"
    ring_seconds: int = 20
    user_uuids: list[str] = field(default_factory=list)
    fallback: MenuAction | None = None

    def validate(self) -> None:
        self.label = ascii_label(self.label)
        self.extension = self.extension.strip()
        if not self.label:
            raise PbxRouteError("Nom du groupe manquant", 422)
        if not EXTEN.match(self.extension):
            raise PbxRouteError("Numéro du groupe invalide (2 à 10 chiffres)", 422)
        if self.strategy not in RING_STRATEGIES:
            raise PbxRouteError("Façon de sonner inconnue", 422)
        if len(set(self.user_uuids)) != len(self.user_uuids):
            raise PbxRouteError("Un poste apparaît deux fois", 422)


def _members(user_uuids: list[str]) -> list[dict]:
    return [{"uuid": uuid, "priority": index} for index, uuid in enumerate(user_uuids)]


async def _check_users(client: PbxClient, user_uuids: list[str]) -> None:
    known = {u.get("uuid") for u in await client.users()}
    if any(uuid not in known for uuid in user_uuids):
        raise PbxRouteError("Poste introuvable", 404)


async def create_group(organization_id: int, spec: NewGroup, **client_kwargs) -> dict:
    spec.validate()
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        await _check_users(client, spec.user_uuids)
        context = await _internal_context(client)
        if await client.extensions(exten=spec.extension, context=context):
            raise PbxRouteError(f"Le numéro {spec.extension} est déjà utilisé", 409)
        ring = max(5, min(spec.ring_seconds, 120))
        group = await client.create_group(
            {
                "label": spec.label,
                "ring_strategy": spec.strategy,
                "user_timeout": ring,
                # Ringing in turn: give every member a chance before giving up.
                "timeout": ring
                if spec.strategy == "all"
                else ring * max(1, len(spec.user_uuids)),
                "enabled": True,
            }
        )
        try:
            extension = await client.create_extension(spec.extension, context)
            await client.associate_group_extension(group["uuid"], extension["id"])
            if spec.user_uuids:
                await client.set_group_users(group["uuid"], _members(spec.user_uuids))
        except PbxError:
            await client.delete_group(group["uuid"])
            raise
    if spec.fallback is not None:
        await set_group_fallback(
            organization_id, group["uuid"], spec.fallback, **client_kwargs
        )
    return {
        "uuid": group["uuid"],
        "id": group["id"],
        "label": spec.label,
        "extension": spec.extension,
    }


async def set_group_members(
    organization_id: int, group_uuid: str, user_uuids: list[str], **client_kwargs
) -> None:
    if len(set(user_uuids)) != len(user_uuids):
        raise PbxRouteError("Un poste apparaît deux fois", 422)
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        await _check_users(client, user_uuids)
        await client.set_group_users(group_uuid, _members(user_uuids))


async def set_group_fallback(
    organization_id: int, group_uuid: str, action: MenuAction | None, **client_kwargs
) -> None:
    """Nobody answers in the group → ``action`` (``None``: the call ends)."""
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        group = await client.group(group_uuid)
        key = group_key(group["id"])
        destination = await fallback_destination(
            organization_id,
            connection,
            action,
            key=key,
            metadata_key=GROUP_METADATA_KEY,
            meta={"group_id": group["id"], "label": f"Groupe {group.get('label')}"},
        )
        await client.set_group_fallbacks(
            group_uuid, {"noanswer_destination": destination}
        )
    if action is None or action.type != "ai":
        await _clear_ai_destination(connection, key)


def _describe(destination: dict | None) -> dict | None:
    if not destination:
        return None
    kind = destination.get("type")
    for key in (
        "queue_id",
        "group_id",
        "user_id",
        "voicemail_id",
        "ivr_id",
        "conference_id",
    ):
        if destination.get(key) is not None:
            return {"type": kind, "target_id": destination[key]}
    return {"type": kind, "target_id": None}


async def list_groups(organization_id: int, **client_kwargs) -> list[dict[str, Any]]:
    from api.db import db_client
    from api.services.pbx.service import _ai_phone_rows

    connection = await _connection(organization_id)
    ai = {}
    for row in await _ai_phone_rows(connection):
        meta = (row.extra_metadata or {}).get(GROUP_METADATA_KEY)
        if meta and row.is_active and row.inbound_workflow_id:
            workflow = await db_client.get_workflow(
                row.inbound_workflow_id, organization_id=organization_id
            )
            ai[meta.get("group_id")] = {
                "type": "ai",
                "target_id": row.inbound_workflow_id,
                "workflow_name": workflow.name if workflow else None,
            }
    async with client_for(connection, **client_kwargs) as client:
        groups = await client.groups()
    result = []
    for group in groups:
        fallback = (group.get("fallbacks") or {}).get("noanswer_destination")
        members = (group.get("members") or {}).get("users") or []
        result.append(
            {
                "id": group.get("id"),
                "uuid": group.get("uuid"),
                "label": group.get("label") or group.get("name"),
                "extensions": [e.get("exten") for e in group.get("extensions") or []],
                "strategy": group.get("ring_strategy"),
                "ring_seconds": group.get("user_timeout"),
                "members": [
                    {
                        "uuid": m.get("uuid"),
                        "name": " ".join(
                            p for p in (m.get("firstname"), m.get("lastname")) if p
                        ).strip()
                        or m.get("uuid"),
                    }
                    for m in sorted(members, key=lambda m: m.get("priority") or 0)
                ],
                "fallback": ai.get(group.get("id"))
                if (fallback or {}).get("type") == "custom"
                else _describe(fallback),
            }
        )
    return result


async def delete_group(organization_id: int, group_uuid: str, **client_kwargs) -> None:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        group = await client.group(group_uuid)
        await client.delete_group(group_uuid)
        for extension in group.get("extensions") or []:
            if extension.get("id"):
                try:
                    await client.delete_extension(extension["id"])
                except PbxError as error:
                    if error.status != 404:
                        raise
    await _clear_ai_destination(connection, group_key(group["id"]))

"""Per-extension call handling: forwards, do-not-disturb, and where the call
goes when the person does not pick up (voicemail, colleague, queue… or an AI
agent that takes a message and answers questions).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from api.services.pbx.admin import AI_KEY_PREFIX, _clear_ai_destination
from api.services.pbx.groups import _describe, fallback_destination
from api.services.pbx.ivr import MenuAction
from api.services.pbx.service import (
    PbxRouteError,
    _ai_phone_rows,
    _connection,
    client_for,
)

USER_METADATA_KEY = "pbx_user"
FORWARD_KINDS = ("unconditional", "busy", "noanswer")
_DESTINATION = re.compile(r"^\+?[0-9*#]{2,32}$")


class Forward(BaseModel):
    enabled: bool = False
    destination: str = Field(default="", max_length=40)

    @field_validator("destination")
    @classmethod
    def _clean(cls, value: str) -> str:
        value = re.sub(r"[\s.\-()]", "", value or "")
        if value and not _DESTINATION.match(value):
            raise ValueError("Numéro de renvoi invalide")
        return value


class UserCallSettings(BaseModel):
    unconditional: Forward = Field(default_factory=Forward)
    busy: Forward = Field(default_factory=Forward)
    noanswer: Forward = Field(default_factory=Forward)
    dnd: bool = False
    # When the extension does not answer, is busy or unreachable.
    unanswered: MenuAction | None = None
    unanswered_mode: Literal["keep", "set"] = "set"

    def check(self) -> None:
        for kind in FORWARD_KINDS:
            forward: Forward = getattr(self, kind)
            if forward.enabled and not forward.destination:
                raise PbxRouteError("Indiquez le numéro de renvoi", 422)


def user_key(user_id: int) -> str:
    return f"{AI_KEY_PREFIX}u{user_id}"


async def _user(client, user_id: int) -> dict:
    for user in await client.users():
        if user.get("id") == user_id:
            return user
    raise PbxRouteError("Poste introuvable", 404)


async def read_user_settings(
    organization_id: int, user_id: int, **client_kwargs
) -> dict[str, Any]:
    from api.db import db_client

    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        user = await _user(client, user_id)
        forwards = await client.user_forwards(user_id) or {}
        services = await client.user_services(user_id) or {}
        fallbacks = await client.user_fallbacks(user_id) or {}
    unanswered = _describe(fallbacks.get("noanswer_destination"))
    if unanswered and unanswered["type"] == "custom":
        unanswered = None
        for row in await _ai_phone_rows(connection):
            meta = (row.extra_metadata or {}).get(USER_METADATA_KEY)
            if meta and meta.get("user_id") == user_id and row.inbound_workflow_id:
                workflow = await db_client.get_workflow(
                    row.inbound_workflow_id, organization_id=organization_id
                )
                unanswered = {
                    "type": "ai",
                    "target_id": row.inbound_workflow_id,
                    "workflow_name": workflow.name if workflow else None,
                }
    return {
        "user_id": user_id,
        "name": " ".join(p for p in (user.get("firstname"), user.get("lastname")) if p),
        "forwards": {
            kind: {
                "enabled": bool((forwards.get(kind) or {}).get("enabled")),
                "destination": (forwards.get(kind) or {}).get("destination") or "",
            }
            for kind in FORWARD_KINDS
        },
        "dnd": bool((services.get("dnd") or {}).get("enabled")),
        "unanswered": unanswered,
    }


async def save_user_settings(
    organization_id: int, user_id: int, settings: UserCallSettings, **client_kwargs
) -> dict[str, Any]:
    settings.check()
    connection = await _connection(organization_id)
    key = user_key(user_id)
    async with client_for(connection, **client_kwargs) as client:
        user = await _user(client, user_id)
        await client.set_user_forwards(
            user_id,
            {
                kind: {
                    "enabled": getattr(settings, kind).enabled,
                    "destination": getattr(settings, kind).destination or None,
                }
                for kind in FORWARD_KINDS
            },
        )
        current = await client.user_services(user_id) or {}
        await client.set_user_services(
            user_id,
            {
                "dnd": {"enabled": settings.dnd},
                "incallfilter": {
                    "enabled": bool((current.get("incallfilter") or {}).get("enabled"))
                },
            },
        )
        if settings.unanswered_mode == "set":
            name = " ".join(
                p for p in (user.get("firstname"), user.get("lastname")) if p
            )
            destination = await fallback_destination(
                organization_id,
                connection,
                settings.unanswered,
                key=key,
                metadata_key=USER_METADATA_KEY,
                meta={"user_id": user_id, "label": f"Poste {name or user_id}"},
            )
            current_fallbacks = await client.user_fallbacks(user_id) or {}
            await client.set_user_fallbacks(
                user_id,
                {
                    **{
                        k: v
                        for k, v in current_fallbacks.items()
                        if k.endswith("_destination")
                    },
                    "noanswer_destination": destination,
                    "busy_destination": destination,
                    "congestion_destination": destination,
                    "fail_destination": destination,
                },
            )
    if settings.unanswered_mode == "set" and (
        settings.unanswered is None or settings.unanswered.type != "ai"
    ):
        await _clear_ai_destination(connection, key)
    return await read_user_settings(organization_id, user_id, **client_kwargs)

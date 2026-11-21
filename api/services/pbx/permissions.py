"""Call restrictions of the enterprise PBX ("permissions d'appel").

A restriction lists number patterns and the extensions it applies to. In
``deny`` mode those extensions cannot call the patterns (unless the optional
PIN is typed); in ``allow`` mode they can call only those patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from api.services.pbx.client import PbxError
from api.services.pbx.service import PbxRouteError, _connection, client_for

# The PBX's own validator for restriction patterns.
PATTERN = re.compile(r"^(?:_?\+?[0-9NXZ*#\-\[\]]+[.!]?){1,40}$")
PIN = re.compile(r"^[0-9#*]{1,40}$")

PRESETS = [
    {
        "id": "international",
        "label": "Pas d'appels internationaux",
        "mode": "deny",
        "patterns": ["_00.", "_+X."],
    },
    {
        "id": "premium",
        "label": "Pas de numéros surtaxés (08…)",
        "mode": "deny",
        "patterns": ["_08."],
    },
    {
        "id": "internal",
        "label": "Appels internes uniquement",
        "mode": "deny",
        "patterns": ["_0.", "_+X."],
    },
]


@dataclass
class NewRestriction:
    name: str
    patterns: list[str]
    mode: Literal["allow", "deny"] = "deny"
    user_ids: list[int] = field(default_factory=list)
    pin: str = ""
    description: str = ""

    def validate(self) -> None:
        self.name = self.name.strip()
        self.patterns = [p.strip() for p in self.patterns if p.strip()]
        if not self.name:
            raise PbxRouteError("Nom de la restriction manquant", 422)
        if not 1 <= len(self.patterns) <= 50:
            raise PbxRouteError("Entre 1 et 50 motifs", 422)
        for pattern in self.patterns:
            if not PATTERN.match(pattern):
                raise PbxRouteError(f"Motif « {pattern} » invalide", 422)
        if len(set(self.patterns)) != len(self.patterns):
            raise PbxRouteError("Un motif apparaît deux fois", 422)
        if self.pin and not PIN.match(self.pin):
            raise PbxRouteError("Code de dérogation : chiffres, * et # uniquement", 422)
        if len(set(self.user_ids)) != len(self.user_ids):
            raise PbxRouteError("Un poste apparaît deux fois", 422)


def _shape(permission: dict) -> dict[str, Any]:
    return {
        "id": permission.get("id"),
        "name": permission.get("name"),
        "mode": permission.get("mode") or "deny",
        "patterns": list(permission.get("extensions") or []),
        "enabled": permission.get("enabled", True),
        "has_pin": bool(permission.get("password")),
        "description": permission.get("description"),
        "users": [
            {
                "uuid": u.get("uuid"),
                "name": " ".join(
                    p for p in (u.get("firstname"), u.get("lastname")) if p
                ).strip()
                or u.get("uuid"),
            }
            for u in permission.get("users") or []
        ],
    }


async def list_restrictions(organization_id: int, **client_kwargs) -> list[dict]:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        return [_shape(p) for p in await client.call_permissions()]


async def create_restriction(
    organization_id: int, spec: NewRestriction, **client_kwargs
) -> dict[str, Any]:
    spec.validate()
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        known = {u.get("id") for u in await client.users()}
        if any(user_id not in known for user_id in spec.user_ids):
            raise PbxRouteError("Poste introuvable", 404)
        permission = await client.create_call_permission(
            {
                "name": spec.name[:128],
                "mode": spec.mode,
                "extensions": spec.patterns,
                "password": spec.pin or None,
                "enabled": True,
                "description": spec.description or None,
            }
        )
        try:
            for user_id in spec.user_ids:
                await client.associate_user_call_permission(user_id, permission["id"])
        except PbxError:
            await client.delete_call_permission(permission["id"])
            raise
        return _shape(await client.call_permission(permission["id"]))


async def set_restriction_users(
    organization_id: int, permission_id: int, user_ids: list[int], **client_kwargs
) -> dict[str, Any]:
    """Make exactly ``user_ids`` subject to the restriction."""
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        permission = await client.call_permission(permission_id)
        users = {u.get("uuid"): u.get("id") for u in await client.users()}
        current = {
            users.get(u.get("uuid"))
            for u in permission.get("users") or []
            if users.get(u.get("uuid")) is not None
        }
        wanted = set(user_ids)
        if any(user_id not in users.values() for user_id in wanted):
            raise PbxRouteError("Poste introuvable", 404)
        for user_id in sorted(wanted - current):
            await client.associate_user_call_permission(user_id, permission_id)
        for user_id in sorted(current - wanted):
            await client.dissociate_user_call_permission(user_id, permission_id)
        return _shape(await client.call_permission(permission_id))


async def delete_restriction(
    organization_id: int, permission_id: int, **client_kwargs
) -> None:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        await client.delete_call_permission(permission_id)

"""Conference rooms of the enterprise PBX, with live control of who is in.

A room has an internal number (and can be given a public one from the
Numbers tab), an optional participant PIN and organizer PIN, a size limit and
announcements. While a meeting runs, the console lists participants and can
mute, unmute or remove them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from api.services.pbx.admin import EXTEN, _internal_context
from api.services.pbx.client import PbxError
from api.services.pbx.service import PbxRouteError, _connection, client_for

PIN = re.compile(r"^[0-9]{4,12}$")


@dataclass
class NewConference:
    name: str
    extension: str
    pin: str = ""
    admin_pin: str = ""
    max_users: int = 0  # 0 = no limit
    record: bool = False
    announce_join_leave: bool = True
    announce_user_count: bool = True

    def validate(self) -> None:
        self.name = self.name.strip()
        self.extension = self.extension.strip()
        if not self.name:
            raise PbxRouteError("Nom de la salle manquant", 422)
        if not EXTEN.match(self.extension):
            raise PbxRouteError("Numéro de la salle invalide (2 à 10 chiffres)", 422)
        for label, pin in (
            ("participants", self.pin),
            ("organisateur", self.admin_pin),
        ):
            if pin and not PIN.match(pin):
                raise PbxRouteError(f"Code {label} : 4 à 12 chiffres", 422)
        if self.pin and self.pin == self.admin_pin:
            raise PbxRouteError(
                "Le code organisateur doit différer du code participants", 422
            )
        if not 0 <= self.max_users <= 500:
            raise PbxRouteError("Nombre de participants : 0 à 500", 422)


async def create_conference(
    organization_id: int, spec: NewConference, **client_kwargs
) -> dict[str, Any]:
    spec.validate()
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        context = await _internal_context(client)
        if await client.extensions(exten=spec.extension, context=context):
            raise PbxRouteError(f"Le numéro {spec.extension} est déjà utilisé", 409)
        conference = await client.create_conference(
            {
                "name": spec.name[:128],
                "pin": spec.pin or None,
                "admin_pin": spec.admin_pin or None,
                "max_users": spec.max_users,
                "record": spec.record,
                "announce_join_leave": spec.announce_join_leave,
                "announce_user_count": spec.announce_user_count,
                "announce_only_user": True,
                "quiet_join_leave": not spec.announce_join_leave,
            }
        )
        try:
            extension = await client.create_extension(spec.extension, context)
            await client.associate_conference_extension(
                conference["id"], extension["id"]
            )
        except PbxError:
            await client.delete_conference(conference["id"])
            raise
    return {"id": conference["id"], "name": spec.name, "extension": spec.extension}


def _participant(p: dict) -> dict[str, Any]:
    return {
        "id": p.get("id"),
        "name": p.get("caller_id_name") or p.get("caller_id_num") or "Participant",
        "number": p.get("caller_id_num"),
        "muted": bool(p.get("muted")),
        "admin": bool(p.get("admin")),
        "joined_at": p.get("join_time"),
    }


async def list_conferences(organization_id: int, **client_kwargs) -> dict[str, Any]:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        conferences = await client.conferences()
        rooms = []
        live_error = None
        for conference in conferences:
            participants: list[dict] = []
            try:
                participants = [
                    _participant(p)
                    for p in await client.conference_participants(conference["id"])
                ]
            except PbxError as error:
                if error.status != 404:  # 404: nobody in the room
                    live_error = str(error)
            rooms.append(
                {
                    "id": conference.get("id"),
                    "name": conference.get("name") or f"Salle {conference.get('id')}",
                    "extensions": [
                        e.get("exten") for e in conference.get("extensions") or []
                    ],
                    "has_pin": bool(conference.get("pin")),
                    "has_admin_pin": bool(conference.get("admin_pin")),
                    "max_users": conference.get("max_users") or 0,
                    "record": bool(conference.get("record")),
                    "participants": participants,
                }
            )
    return {"conferences": rooms, "live_error": live_error}


async def delete_conference(
    organization_id: int, conference_id: int, **client_kwargs
) -> None:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        conference = next(
            (c for c in await client.conferences() if c.get("id") == conference_id),
            None,
        )
        if conference is None:
            raise PbxRouteError("Salle introuvable", 404)
        await client.delete_conference(conference_id)
        for extension in conference.get("extensions") or []:
            if extension.get("id"):
                try:
                    await client.delete_extension(extension["id"])
                except PbxError as error:
                    if error.status != 404:
                        raise


async def participant_action(
    organization_id: int,
    conference_id: int,
    participant_id: str,
    action: str,
    **client_kwargs,
) -> None:
    if action not in {"mute", "unmute", "kick"}:
        raise PbxRouteError("Action inconnue", 422)
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        if action == "kick":
            await client.kick_participant(conference_id, participant_id)
        else:
            await client.mute_participant(
                conference_id, participant_id, action == "mute"
            )

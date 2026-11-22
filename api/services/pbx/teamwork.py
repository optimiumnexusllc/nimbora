"""Working as a team on the enterprise PBX.

- **Interception** (call pickup groups): a colleague picks up a call ringing on
  another member's phone by dialling ``*8``.
- **Parcage** (parking lots): a call is transferred to the lot's number, waits
  in a slot (701, 702…) announced to the employee, and anyone picks it up by
  dialling that slot. A call left too long rings back the employee.
- **Interphone et annonces** (paging): ``*11`` followed by the paging number
  rings the members' phones, which answer by themselves. With one member and
  both-way audio it is an intercom; with several, an announcement.
- **Horaires des routes sortantes**: an outbound route follows a schedule
  (the ones made for opening hours); outside it, outgoing calls are refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from api.services.pbx.admin import EXTEN, _internal_context
from api.services.pbx.client import PbxClient, PbxError
from api.services.pbx.service import PbxRouteError, _connection, client_for

PICKUP_CODE = "*8"
PAGING_PREFIX = "*11"
PAGING_NUMBER = re.compile(r"^[0-9]{1,8}$")


def _users(items: list[str]) -> list[dict]:
    return [{"uuid": uuid} for uuid in dict.fromkeys(u for u in items if u)]


def _names(entries: dict | None, by_uuid: dict[str, dict]) -> list[dict]:
    """Users of a pickup interceptors/targets or a paging members/callers block."""
    users = (entries or {}).get("users") if isinstance(entries, dict) else entries
    result = []
    for u in users or []:
        known = by_uuid.get(u.get("uuid"), {})
        name = " ".join(
            p
            for p in (
                u.get("firstname") or known.get("firstname"),
                u.get("lastname") or known.get("lastname"),
            )
            if p
        ).strip()
        result.append(
            {
                "uuid": u.get("uuid"),
                "name": name or known.get("email") or u.get("uuid"),
                "extension": known.get("extension"),
            }
        )
    return result


async def _users_by_uuid(client: PbxClient) -> dict[str, dict]:
    return {u["uuid"]: u for u in await client.users() if u.get("uuid")}


def _check_members(members: list[str], known: dict[str, dict], label: str) -> None:
    unknown = [m for m in members if m not in known]
    if unknown:
        raise PbxRouteError(f"{label} : poste inconnu ({', '.join(unknown)})", 422)


# ------------------------------------------------------------------ pickup


@dataclass
class NewPickupGroup:
    name: str
    members: list[str] = field(default_factory=list)

    def validate(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise PbxRouteError("Nom du groupe d'interception manquant", 422)
        if len(set(self.members)) < 2:
            raise PbxRouteError(
                "Un groupe d'interception réunit au moins deux postes", 422
            )


async def list_pickup_groups(organization_id: int, **client_kwargs) -> list[dict]:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        groups = await client.callpickups()
        users = await _users_by_uuid(client)
    return [
        {
            "id": g.get("id"),
            "name": g.get("name"),
            "enabled": g.get("enabled", True),
            "members": _names(g.get("targets"), users),
            "code": PICKUP_CODE,
        }
        for g in groups
    ]


async def create_pickup_group(
    organization_id: int, spec: NewPickupGroup, **client_kwargs
) -> dict[str, Any]:
    """Every member can pick up a call ringing on any other member."""
    spec.validate()
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        users = await _users_by_uuid(client)
        _check_members(spec.members, users, "Groupe d'interception")
        group = await client.create_callpickup(
            {"name": spec.name[:128], "enabled": True}
        )
        try:
            members = _users(spec.members)
            await client.set_callpickup_users(group["id"], "interceptors", members)
            await client.set_callpickup_users(group["id"], "targets", members)
        except PbxError:
            await client.delete_callpickup(group["id"])
            raise
    return {"id": group["id"], "name": spec.name, "code": PICKUP_CODE}


async def delete_pickup_group(
    organization_id: int, group_id: int, **client_kwargs
) -> None:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        await client.delete_callpickup(group_id)


# ----------------------------------------------------------------- parking


@dataclass
class NewParkingLot:
    name: str
    extension: str
    slots_start: str
    slots_end: str
    timeout: int = 45  # seconds before the call rings the employee back

    def validate(self) -> None:
        self.name = self.name.strip()
        for value in (self.extension, self.slots_start, self.slots_end):
            if not EXTEN.match(value or ""):
                raise PbxRouteError("Numéros du parking : 2 à 10 chiffres", 422)
        if len(self.slots_start) != len(self.slots_end) or int(self.slots_start) > int(
            self.slots_end
        ):
            raise PbxRouteError(
                "Places : la première doit précéder la dernière (même longueur)", 422
            )
        if int(self.slots_end) - int(self.slots_start) >= 200:
            raise PbxRouteError("200 places au plus", 422)
        if int(self.slots_start) <= int(self.extension) <= int(self.slots_end):
            raise PbxRouteError(
                "Le numéro du parking ne peut pas être une de ses places", 422
            )
        if not 10 <= self.timeout <= 3600:
            raise PbxRouteError("Délai avant rappel : 10 à 3600 secondes", 422)
        if not self.name:
            self.name = f"Parking {self.extension}"


async def list_parking_lots(organization_id: int, **client_kwargs) -> list[dict]:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        lots = await client.parkinglots()
    return [
        {
            "id": lot.get("id"),
            "name": lot.get("name"),
            "extension": next(
                (e.get("exten") for e in lot.get("extensions") or []), None
            ),
            "slots_start": lot.get("slots_start"),
            "slots_end": lot.get("slots_end"),
            "timeout": lot.get("timeout"),
        }
        for lot in lots
    ]


async def create_parking_lot(
    organization_id: int, spec: NewParkingLot, **client_kwargs
) -> dict[str, Any]:
    spec.validate()
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        context = await _internal_context(client)
        if await client.extensions(exten=spec.extension, context=context):
            raise PbxRouteError(f"Le numéro {spec.extension} est déjà utilisé", 409)
        lot = await client.create_parkinglot(
            {
                "name": spec.name[:128],
                "slots_start": spec.slots_start,
                "slots_end": spec.slots_end,
                "timeout": spec.timeout,
                "music_on_hold": "default",
            }
        )
        try:
            extension = await client.create_extension(spec.extension, context)
            await client.associate_parkinglot_extension(lot["id"], extension["id"])
        except PbxError:
            await client.delete_parkinglot(lot["id"])
            raise
    return {"id": lot["id"], "name": spec.name, "extension": spec.extension}


async def delete_parking_lot(
    organization_id: int, lot_id: int, **client_kwargs
) -> None:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        lot = next(
            (x for x in await client.parkinglots() if x.get("id") == lot_id), None
        )
        if lot is None:
            raise PbxRouteError("Parking introuvable", 404)
        await client.delete_parkinglot(lot_id)
        for extension in lot.get("extensions") or []:
            if extension.get("id"):
                try:
                    await client.delete_extension(extension["id"])
                except PbxError as error:
                    if error.status != 404:
                        raise


async def parking_extensions(client: PbxClient) -> list[dict]:
    """Lots the Softphone offers in « Parquer » (best effort)."""
    try:
        lots = await client.parkinglots()
    except PbxError:
        return []
    return [
        {"name": lot.get("name"), "extension": e.get("exten")}
        for lot in lots
        for e in (lot.get("extensions") or [])[:1]
        if e.get("exten")
    ]


def asterisk_lot_name(lot: dict) -> str:
    """The engine names each lot after its id in Asterisk (res_parking)."""
    return f"parkinglot-{lot['id']}"


def _waiting_seconds(parked_at: str | None) -> int:
    if not parked_at:
        return 0
    try:
        since = datetime.fromisoformat(parked_at.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - since).total_seconds()))


async def parked_calls(client: PbxClient) -> list[dict]:
    """Calls waiting in the company's lots, with the slot to dial to take one.

    Read from wazo-calld, lot by lot: it only knows the company's own lots
    (tenant aware), unlike the AMI, which also refuses any token that is not
    the master tenant's (lab step 15).
    """
    try:
        lots = await client.parkinglots()
    except PbxError:
        return []
    parked = []
    for lot in lots:
        try:
            data = await client.parkinglot_calls(lot["id"])
        except PbxError:
            continue
        for call in data.get("calls") or []:
            name = call.get("caller_id_name") or None
            if name in ("<unknown>", "unknown"):
                name = None
            parked.append(
                {
                    "lot": lot.get("name"),
                    "slot": str(call.get("slot") or ""),
                    "number": call.get("caller_id_num") or "",
                    "name": name,
                    "waiting_seconds": _waiting_seconds(call.get("parked_at")),
                    "parked_by": call.get("parker_caller_id_num") or None,
                }
            )
    return sorted(parked, key=lambda p: p["slot"])


async def organization_parked_calls(
    organization_id: int, **client_kwargs
) -> list[dict]:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        return await parked_calls(client)


# ------------------------------------------------------------------ paging


@dataclass
class NewPaging:
    name: str
    number: str
    members: list[str] = field(default_factory=list)
    # Who may call it; empty = every extension of the company.
    callers: list[str] = field(default_factory=list)
    duplex: bool = True  # both ways: an intercom; one way: an announcement

    def validate(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise PbxRouteError("Nom manquant", 422)
        if not PAGING_NUMBER.match(self.number or ""):
            raise PbxRouteError("Numéro d'interphone : 1 à 8 chiffres", 422)
        if not self.members:
            raise PbxRouteError("Choisissez au moins un poste qui reçoit", 422)


async def list_pagings(organization_id: int, **client_kwargs) -> list[dict]:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        pagings = await client.pagings()
        users = await _users_by_uuid(client)
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "number": p.get("number"),
            "dial": f"{PAGING_PREFIX}{p.get('number')}",
            "duplex": bool(p.get("duplex")),
            "kind": "intercom"
            if p.get("duplex") and len((p.get("members") or {}).get("users") or []) == 1
            else "announcement",
            "members": _names(p.get("members"), users),
            # Everyone may call it: shown as no restriction.
            "callers": []
            if {u.get("uuid") for u in (p.get("callers") or {}).get("users") or []}
            >= set(users)
            else _names(p.get("callers"), users),
        }
        for p in pagings
    ]


async def create_paging(
    organization_id: int, spec: NewPaging, **client_kwargs
) -> dict[str, Any]:
    spec.validate()
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        users = await _users_by_uuid(client)
        _check_members(spec.members, users, "Postes qui reçoivent")
        _check_members(spec.callers, users, "Postes qui appellent")
        if any(str(p.get("number")) == spec.number for p in await client.pagings()):
            raise PbxRouteError(f"L'interphone {spec.number} existe déjà", 409)
        paging = await client.create_paging(
            {
                "name": spec.name[:128],
                "number": spec.number,
                "duplex": spec.duplex,
                "ignore_forward": True,
                "enabled": True,
                "announce_caller": True,
                "caller_notification": True,
            }
        )
        try:
            await client.set_paging_users(paging["id"], "members", _users(spec.members))
            # The engine only lets listed callers page the group: « everyone »
            # means every extension of the company (lab step 15: an empty list
            # refused every caller, « Unable to find paging caller entry »).
            await client.set_paging_users(
                paging["id"], "callers", _users(spec.callers or list(users))
            )
        except PbxError:
            await client.delete_paging(paging["id"])
            raise
    return {
        "id": paging["id"],
        "name": spec.name,
        "dial": f"{PAGING_PREFIX}{spec.number}",
    }


async def delete_paging(organization_id: int, paging_id: int, **client_kwargs) -> None:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        await client.delete_paging(paging_id)


# -------------------------------------------------- outbound route schedules


def outbound_schedule_name(organization_id: int) -> str:
    from api.services.pbx.admin import SCHEDULE_NAME_PREFIX

    return f"{SCHEDULE_NAME_PREFIX}-sortie-{organization_id}"


async def _ensure_outbound_schedule(client: PbxClient, organization_id: int) -> int:
    """The company's opening hours (« Mon entreprise »), as a schedule of its
    own whose closed destination refuses the call: the inbound schedule sends
    callers to the AI after hours, which makes no sense for an outgoing call."""
    from api.services.business.profile import get_business_profile
    from api.services.pbx.admin import schedule_from_profile

    profile = await get_business_profile(organization_id)
    if not profile.opening_hours:
        raise PbxRouteError(
            "Renseignez d'abord les horaires dans « Mon entreprise »", 409
        )
    refuse = {"type": "hangup", "cause": "congestion"}
    body = {
        "name": outbound_schedule_name(organization_id),
        "enabled": True,
        "closed_destination": refuse,
        **schedule_from_profile(profile),
    }
    for period in body["exceptional_periods"]:
        period["destination"] = refuse
    existing = next(
        (x for x in await client.schedules() if x.get("name") == body["name"]), None
    )
    if existing:
        await client.update_schedule(existing["id"], body)
        return existing["id"]
    return (await client.create_schedule(body))["id"]


async def set_outbound_route_hours(
    organization_id: int, outcall_id: int, opening_hours_only: bool, **client_kwargs
) -> dict[str, Any]:
    """Outgoing calls through this route only during the opening hours (or
    at any time). Later changes of hours in « Mon entreprise » reach the
    schedule on their own (``admin.refresh_schedules``)."""
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        outcall = next(
            (o for o in await client.outcalls() if o.get("id") == outcall_id), None
        )
        if outcall is None:
            raise PbxRouteError("Route sortante introuvable", 404)
        schedule_id = (
            await _ensure_outbound_schedule(client, organization_id)
            if opening_hours_only
            else None
        )
        for current in outcall.get("schedules") or []:
            if current.get("id") != schedule_id:
                await client.dissociate_outcall_schedule(outcall_id, current["id"])
        if schedule_id is not None and not any(
            x.get("id") == schedule_id for x in outcall.get("schedules") or []
        ):
            await client.associate_outcall_schedule(outcall_id, schedule_id)
    return {
        "id": outcall_id,
        "opening_hours_only": opening_hours_only,
        "schedule_id": schedule_id,
    }

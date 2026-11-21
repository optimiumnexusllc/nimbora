"""AI agent → enterprise PBX: hand a caller to a queue or an extension.

An AI agent answering through the PBX's Asterisk (ARI) transfers with the
destination ``pbx-queue:<queue id>`` or ``pbx-extension:<extension>``. The
target is looked up on the company's PBX (tenant-scoped API), and the call
enters the PBX's own dialplan through ``Local/<exten>@<context>`` — exactly
as if a phone of the company had dialled it: queue strategy, music on hold,
agents, overflow, voicemail all apply.

The human who picks up gets the AI's handoff card (reason, summary,
sentiment, next step, collected data, transcript): in NIMBORA Softphone when
the call rings, on the supervision console, and — on any desk phone — in the
caller name, which carries the customer's number.

The transfer is only allowed when the call really runs on the PBX's
Asterisk (the ARI configuration linked to the PBX connection): dialling a
PBX context on another Asterisk would reach nothing, or someone else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from api.services.contact_center.destinations import ContactCenterDestinationError
from api.services.pbx.client import PbxError
from api.services.pbx.service import PbxNotConfigured, _connection, client_for

QUEUE_PREFIX = "pbx-queue:"
EXTENSION_PREFIX = "pbx-extension:"
CARD_KEY_PREFIX = "pbx:"  # handoff cards: queue_slug "pbx:q<id>" / "pbx:e<exten>"
_EXTEN_RE = re.compile(r"^[0-9*#+]{1,20}$")
_CONTEXT_RE = re.compile(r"^[A-Za-z0-9_-]{1,79}$")
_CALLER_NAME_RE = re.compile(r'["<>\\\r\n]')


class PbxTransferError(ContactCenterDestinationError):
    """The PBX destination is not allowed or does not exist for this tenant."""


@dataclass(frozen=True)
class PbxTarget:
    kind: str  # "queue" | "extension"
    value: str  # queue id or extension number
    exten: str
    context: str
    label: str

    @property
    def dial_string(self) -> str:
        return f"Local/{self.exten}@{self.context}"

    @property
    def card_key(self) -> str:
        return card_key(self.kind, self.value)


def card_key(kind: str, value: str) -> str:
    """How a handoff card names its PBX target (``pbx:q3``, ``pbx:e1001``)."""
    return f"{CARD_KEY_PREFIX}{'q' if kind == 'queue' else 'e'}{value}"[:48]


def parse_destination(destination: Any) -> tuple[str, str] | None:
    """``("queue", "3")`` / ``("extension", "1001")``, or None if not a PBX target."""
    text = str(destination or "").strip()
    lowered = text.lower()
    if lowered.startswith(QUEUE_PREFIX):
        value = text[len(QUEUE_PREFIX) :].strip()
        if not re.fullmatch(r"\d{1,9}", value):
            raise PbxTransferError(f"Invalid PBX queue: {value!r}")
        return "queue", value
    if lowered.startswith(EXTENSION_PREFIX):
        value = text[len(EXTENSION_PREFIX) :].strip()
        if not _EXTEN_RE.fullmatch(value):
            raise PbxTransferError(f"Invalid PBX extension: {value!r}")
        return "extension", value
    return None


def _same_endpoint(a: str | None, b: str | None) -> bool:
    def norm(url: str | None) -> str:
        return (url or "").strip().rstrip("/").lower()

    return bool(norm(a)) and norm(a) == norm(b)


async def _assert_call_on_pbx(
    connection, organization_id: int, ari_endpoint: str | None
):
    from api.db import db_client

    if not connection.ari_configuration_id:
        raise PbxTransferError(
            "No ARI configuration is linked to the company PBX: AI calls do not run on it"
        )
    ari = await db_client.get_telephony_configuration_for_org(
        connection.ari_configuration_id, organization_id
    )
    endpoint = ((ari.credentials or {}) if ari else {}).get("ari_endpoint")
    if not _same_endpoint(endpoint, ari_endpoint):
        raise PbxTransferError(
            "This call does not run on the company PBX: it cannot be handed to a PBX queue"
        )


def _checked(exten: Any, context: Any) -> tuple[str, str]:
    exten, context = str(exten or ""), str(context or "")
    if not _EXTEN_RE.fullmatch(exten) or not _CONTEXT_RE.fullmatch(context):
        raise PbxTransferError("Unexpected extension or context on the PBX")
    return exten, context


async def resolve(
    organization_id: int,
    kind: str,
    value: str,
    *,
    ari_endpoint: str | None,
    **client_kwargs,
) -> PbxTarget:
    """Find the target on the tenant's PBX and check the call can reach it."""
    try:
        connection = await _connection(organization_id)
    except PbxNotConfigured as error:
        raise PbxTransferError("No PBX is connected for this organization") from error
    await _assert_call_on_pbx(connection, organization_id, ari_endpoint)
    async with client_for(connection, **client_kwargs) as client:
        try:
            if kind == "queue":
                queue = await client.queue(int(value))
                extension = next(iter(queue.get("extensions") or []), None)
                if not extension:
                    raise PbxTransferError("This PBX queue has no number to dial")
                exten, context = _checked(
                    extension.get("exten"), extension.get("context")
                )
                label = queue.get("label") or queue.get("name") or f"File {value}"
                return PbxTarget("queue", value, exten, context, str(label))
            for user in await client.users():
                for line in user.get("lines") or []:
                    for extension in line.get("extensions") or []:
                        if str(extension.get("exten")) == value:
                            exten, context = _checked(
                                extension.get("exten"), extension.get("context")
                            )
                            name = " ".join(
                                p
                                for p in (user.get("firstname"), user.get("lastname"))
                                if p
                            )
                            return PbxTarget(
                                "extension",
                                value,
                                exten,
                                context,
                                name or f"Poste {value}",
                            )
        except PbxError as error:
            if error.status == 404:
                raise PbxTransferError(f"Unknown PBX {kind}: {value}") from error
            raise
    raise PbxTransferError(f"Unknown PBX extension: {value}")


def caller_id(caller_number: Any, customer_name: Any = None) -> str | None:
    """What the human's phone shows: the customer's number, flagged as from the AI."""
    number = re.sub(r"[^0-9+]", "", str(caller_number or ""))[:20]
    if not number:
        return None
    name = _CALLER_NAME_RE.sub("", str(customer_name or "").strip())[:24]
    label = f"IA · {name}" if name else "IA · Client"
    return f'"{label}" <{number}>'


# --------------------------------------------------------- for humans


async def transfer_targets(
    organization_id: int, **client_kwargs
) -> list[dict[str, Any]]:
    """PBX queues and extensions an AI agent can hand a caller to."""
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        queues = await client.queues()
        users = await client.users()
    targets = [
        {
            "destination": f"{QUEUE_PREFIX}{q.get('id')}",
            "kind": "pbx_queue",
            "label": q.get("label") or q.get("name"),
            "number": next((e.get("exten") for e in q.get("extensions") or []), None),
        }
        for q in queues
        if q.get("id") is not None
    ]
    for user in users:
        if not user.get("extension"):
            continue
        name = " ".join(p for p in (user.get("firstname"), user.get("lastname")) if p)
        targets.append(
            {
                "destination": f"{EXTENSION_PREFIX}{user['extension']}",
                "kind": "pbx_extension",
                "label": name or f"Poste {user['extension']}",
                "number": user["extension"],
            }
        )
    return targets


def serialize_card(card) -> dict[str, Any]:
    """What a human sees of an AI handoff card."""
    return {
        "id": card.id,
        "status": card.status,
        "caller_number": card.caller_number,
        "customer_name": card.customer_name,
        "reason": card.reason,
        "summary": card.summary,
        "sentiment": card.sentiment,
        "next_step": card.next_step,
        "summary_status": card.summary_status,
        "collected_data": card.collected_data or {},
        "transcript": card.transcript or [],
        "target": card.queue_slug,
        "created_at": card.created_at.isoformat() if card.created_at else None,
    }


async def recent_cards(organization_id: int, now: datetime | None = None) -> list:
    """PBX handoff cards still waiting for a human (last few minutes)."""
    from api.db import db_client
    from api.services.contact_center.handoff import recent_cutoff

    cards = await db_client.list_recent_pbx_handoffs(
        organization_id, since=recent_cutoff(now or datetime.now(UTC))
    )
    return cards


def caller_key(number: Any) -> str | None:
    """Last 9 digits: ``0102030405`` and ``+225 01 02 03 04 05`` are the same
    customer (operators present numbers nationally or internationally)."""
    digits = re.sub(r"\D", "", str(number or ""))
    return digits[-9:] if len(digits) >= 8 else None


async def card_for_caller(
    organization_id: int, caller_number: Any, now: datetime | None = None
):
    """The latest pending PBX card for a caller (the call ringing a human)."""
    wanted = caller_key(caller_number)
    if not wanted:
        return None
    for card in await recent_cards(organization_id, now):
        if card.status == "pending" and caller_key(card.caller_number) == wanted:
            return card
    return None

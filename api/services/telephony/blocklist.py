"""Blocked numbers: callers the organization refuses, and people its AI
agents never call ("liste d'opposition").

One list per organization, enforced wherever the platform answers or dials:

* inbound AI calls on every provider (cloud webhooks and the PBX / Asterisk
  over ARI) — the caller is hung up before any agent runs, nothing is billed;
* outbound AI calls — test calls, the public API, campaigns and callbacks.

A person who tells an agent they no longer want to be called (the
``do_not_call`` outcome) is added automatically, outbound only.
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from loguru import logger

from api.services.customer_memory.service import normalize_phone

Direction = Literal["inbound", "outbound", "both"]
DIRECTIONS: tuple[str, ...] = ("inbound", "outbound", "both")
OPT_OUT_DISPOSITIONS = {"do_not_call"}
MAX_IMPORT_ROWS = 5000


class BlockedNumberError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class CallBlocked(Exception):
    """Raised before dialling a number the organization never calls."""

    def __init__(self, number: str, reason: str | None = None):
        super().__init__(
            f"Le numéro {number} est dans la liste des numéros bloqués"
            + (f" ({reason})" if reason else "")
        )
        self.number = number
        self.reason = reason


def normalize_number(raw: str | None) -> str:
    """``+225 07 07-11.22.33`` → ``+2250707112233``; ``00…`` → ``+…``."""
    number = normalize_phone(raw)
    if not number or not re.fullmatch(r"\+?[0-9]{4,20}", number):
        raise BlockedNumberError(f"Numéro invalide : {raw}")
    return number


def _spellings(raw: str | None) -> list[str]:
    """Every stored form that could mean this number."""
    number = normalize_phone(raw)
    if not number:
        return []
    digits = number.lstrip("+")
    return sorted({number, digits, f"+{digits}"})


async def find_block(
    organization_id: int | None, number: str | None, direction: str
) -> object | None:
    """The active entry blocking ``number`` in ``direction``, counted as a hit."""
    from api.db import db_client

    if not organization_id or direction not in ("inbound", "outbound"):
        return None
    spellings = _spellings(number)
    if not spellings:
        return None
    try:
        entry = await db_client.find_blocked_number(
            organization_id, spellings, [direction, "both"]
        )
        if entry is not None:
            await db_client.record_blocked_hit(organization_id, entry.id)
        return entry
    except Exception:
        # A cancelled caller (a campaign batch being stopped) can see its
        # cancellation turned into a driver error ("connection was closed in
        # the middle of operation"). Swallowing it would let the caller go on
        # and dial a contact whose claim is being handed back: re-raise.
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError from None
        logger.opt(exception=True).warning("Blocked number lookup failed")
        return None


async def assert_may_call(organization_id: int | None, number: str | None) -> None:
    """Raise :class:`CallBlocked` when the organization never calls ``number``."""
    entry = await find_block(organization_id, number, "outbound")
    if entry is not None:
        logger.info(
            "Outbound call refused: number is blocked",
            organization_id=organization_id,
            entry_id=entry.id,
        )
        raise CallBlocked(number or "", entry.reason)


@dataclass
class BlockRequest:
    number: str
    direction: Direction = "both"
    reason: str = ""
    expires_at: datetime | None = None


async def block(
    organization_id: int,
    request: BlockRequest,
    *,
    source: str = "manual",
    user_id: int | None = None,
):
    from api.db import db_client

    if request.direction not in DIRECTIONS:
        raise BlockedNumberError("Sens inconnu")
    number = normalize_number(request.number)
    return await db_client.upsert_blocked_number(
        organization_id,
        number,
        {
            "direction": request.direction,
            "reason": (request.reason or "").strip()[:255] or None,
            "source": source,
            "expires_at": request.expires_at,
            "created_by_user_id": user_id,
        },
    )


_TRUE_DIRECTIONS = {
    "entrant": "inbound",
    "inbound": "inbound",
    "sortant": "outbound",
    "outbound": "outbound",
    "les deux": "both",
    "both": "both",
    "": "both",
}


def parse_import(content: str) -> tuple[list[BlockRequest], list[dict]]:
    """``numero;motif;sens`` (comma or semicolon, header optional)."""
    text = (content or "").strip()
    if not text:
        return [], []
    delimiter = (
        ";"
        if text.splitlines()[0].count(";") >= text.splitlines()[0].count(",")
        else ","
    )
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if rows and rows[0] and not normalize_phone(rows[0][0]):
        rows = rows[1:]  # header
    if len(rows) > MAX_IMPORT_ROWS:
        raise BlockedNumberError(f"{MAX_IMPORT_ROWS} lignes au plus par import")
    requests: list[BlockRequest] = []
    errors: list[dict] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not row or not any(cell.strip() for cell in row):
            continue
        raw = row[0].strip()
        direction = _TRUE_DIRECTIONS.get(
            (row[2] if len(row) > 2 else "").strip().lower()
        )
        try:
            number = normalize_number(raw)
        except BlockedNumberError as error:
            errors.append({"line": index, "value": raw, "error": str(error)})
            continue
        if direction is None:
            errors.append(
                {
                    "line": index,
                    "value": raw,
                    "error": "Sens inconnu (entrant, sortant, les deux)",
                }
            )
            continue
        if number in seen:
            continue
        seen.add(number)
        requests.append(
            BlockRequest(
                number=number,
                direction=direction,  # type: ignore[arg-type]
                reason=(row[1] if len(row) > 1 else "").strip(),
            )
        )
    return requests, errors


async def import_numbers(
    organization_id: int, content: str, *, user_id: int | None = None
) -> dict:
    requests, errors = parse_import(content)
    for request in requests:
        await block(organization_id, request, source="import", user_id=user_id)
    return {"imported": len(requests), "errors": errors}


async def block_on_opt_out(workflow_run, organization_id: int) -> bool:
    """The person asked not to be called again: add them, outbound only.

    Never raises; an existing entry keeps its direction widened, not narrowed.
    """
    from api.db import db_client
    from api.services.customer_memory.service import customer_phone_from_context

    try:
        gathered = dict(workflow_run.gathered_context or {})
        outcome = gathered.get("call_disposition")
        mapped = gathered.get("mapped_call_disposition")
        if outcome not in OPT_OUT_DISPOSITIONS and mapped not in OPT_OUT_DISPOSITIONS:
            return False
        phone = customer_phone_from_context(dict(workflow_run.initial_context or {}))
        if not phone:
            return False
        existing = await db_client.find_blocked_number(
            organization_id, _spellings(phone), list(DIRECTIONS)
        )
        if existing is not None and existing.direction in ("outbound", "both"):
            return False
        await block(
            organization_id,
            BlockRequest(
                number=phone,
                direction="both" if existing is not None else "outbound",
                reason=f"A demandé à ne plus être appelé (appel n°{workflow_run.id})",
            ),
            source="caller_request",
        )
        return True
    except Exception:
        logger.opt(exception=True).warning("Opt-out could not be recorded")
        return False


def serialize(entry) -> dict:
    return {
        "id": entry.id,
        "number": entry.number,
        "direction": entry.direction,
        "reason": entry.reason,
        "source": entry.source,
        "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
        "hits": entry.hits or 0,
        "last_hit_at": entry.last_hit_at.isoformat() if entry.last_hit_at else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }

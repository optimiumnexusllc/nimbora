"""Human call minutes on the enterprise PBX, billed with the AI minutes.

A billable human call is a call log of the PBX that was answered, has a
customer on the other end (inbound or outbound, not internal) and was not
taken by one of NIMBORA's AI agents (those are already AI minutes). Its
billable time is the call log's duration (from answer to hang-up).

Two ways in, both idempotent through the call log's id:
* the ``call_log_created`` webhook (``service.handle_event``) as calls end;
* an hourly catch-up reading the PBX call logs since the last one seen, so a
  webhook lost during an outage is never a call left unbilled.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from api.services.pbx.client import PbxError
from loguru import logger

SOURCE = "pbx"
# First catch-up of a connection: how far back to read the call logs.
FIRST_SYNC_LOOKBACK = timedelta(days=2)
# Overlap with the previous run: call logs are written when calls end.
SYNC_OVERLAP = timedelta(minutes=30)
PAGE = 500
MAX_PAGES = 40


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def billable_call(cdr: dict[str, Any], *, ai_routed: bool) -> dict[str, Any] | None:
    """The usage row for a call log, or None when it is not billed."""
    if ai_routed or cdr.get("id") is None or not cdr.get("answered"):
        return None
    direction = (cdr.get("call_direction") or cdr.get("call_drection") or "").lower()
    if direction == "inbound":
        external, staff = cdr.get("source_extension"), cdr.get("destination_name")
    elif direction == "outbound":
        external = cdr.get("destination_extension") or cdr.get("requested_extension")
        staff = cdr.get("source_name")
    else:
        return None  # internal calls are free
    if len(re.sub(r"\D", "", str(external or ""))) < 6:
        return None  # a short number is another extension, not a customer
    seconds = int(float(cdr.get("duration") or 0))
    started = _parse_time(cdr.get("start"))
    if seconds <= 0 or started is None:
        return None
    return {
        "source": SOURCE,
        "external_id": str(cdr["id"]),
        "direction": direction,
        "started_at": started,
        "billable_seconds": seconds,
        "agent_name": (str(staff)[:255] if staff else None),
    }


async def record_call(connection, cdr: dict[str, Any], *, ai_routed: bool) -> bool:
    """Count one call log (no-op if not billable or already counted)."""
    from api.db import db_client

    row = billable_call(cdr, ai_routed=ai_routed)
    if row is None:
        return False
    return await db_client.record_human_call_usage(connection.organization_id, row)


async def _ai_numbers(connection) -> set[str]:
    from api.services.pbx import service

    return set(service._routed_numbers(await service._ai_phone_rows(connection)))


def _is_ai(cdr: dict[str, Any], ai_numbers: set[str]) -> bool:
    from api.services.customer_memory.service import normalize_phone

    return any(
        number and (normalize_phone(number) or number) in ai_numbers
        for number in (cdr.get("requested_extension"), cdr.get("destination_extension"))
    )


async def sync_connection(
    connection, *, now: datetime | None = None, **client_kwargs
) -> dict[str, int]:
    """Read the call logs since the last run and count the billable ones."""
    from api.db import db_client
    from api.services.pbx import service

    now = now or datetime.now(UTC)
    since = (
        connection.usage_synced_at - SYNC_OVERLAP
        if connection.usage_synced_at
        else now - FIRST_SYNC_LOOKBACK
    )
    ai_numbers = await _ai_numbers(connection)
    counted = read = 0
    async with service.client_for(connection, **client_kwargs) as client:
        for page in range(MAX_PAGES):
            items = await client.cdr_since(
                since.isoformat(), limit=PAGE, offset=page * PAGE
            )
            for cdr in items:
                read += 1
                if await record_call(
                    connection, cdr, ai_routed=_is_ai(cdr, ai_numbers)
                ):
                    counted += 1
            if len(items) < PAGE:
                break
    await db_client.save_pbx_connection(
        connection.organization_id, {"usage_synced_at": now}
    )
    return {"read": read, "counted": counted}


async def sync_human_minutes(_ctx=None) -> dict[str, int]:
    """arq cron: catch up on call logs whose webhook was missed."""
    from api.db import db_client

    totals = {"organizations": 0, "counted": 0}
    for connection in await db_client.list_pbx_connections():
        try:
            result = await sync_connection(connection)
        except PbxError as error:
            logger.warning(
                f"[PBX org={connection.organization_id}] Human minutes sync failed: {error}"
            )
            continue
        except Exception:  # noqa: BLE001 - one company never stops the others
            logger.opt(exception=True).warning(
                f"[PBX org={connection.organization_id}] Human minutes sync failed"
            )
            continue
        totals["organizations"] += 1
        totals["counted"] += result["counted"]
    return totals

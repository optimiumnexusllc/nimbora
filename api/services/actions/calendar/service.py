"""The ``book_appointment`` tool: find slots, book, list and cancel.

The agent never invents availability: it asks for slots, reads two or three
out, then books the one the caller picks. Every booking is checked again
against the calendar at booking time (someone may have taken it meanwhile).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from api.services.actions.calendar.providers import (
    CalDAVCalendar,
    CalendarError,
    GoogleCalendar,
    NimboraCalendar,
    day_bounds,
)
from api.services.actions.calendar.slots import (
    Interval,
    SlotRules,
    describe_slot,
    free_slots,
    is_bookable,
    next_open_days,
)
from api.services.actions.common import (
    ActionContext,
    ActionError,
    basic_auth_pair,
    check_outbound_url,
    load_credential,
)
from loguru import logger

REFUSALS = {
    "too_soon": "This time is too soon to book. Offer a later slot.",
    "too_far": "This time is too far ahead. Offer an earlier slot.",
    "closed": "The office is closed at that time. Offer a slot within opening hours.",
    "taken": "This slot was just taken. Offer another free slot.",
}


async def build_backend(ctx: ActionContext, config: dict[str, Any]):
    provider = config.get("provider") or "nimbora"
    if provider == "caldav":
        url = config.get("calendar_url") or ""
        check_outbound_url(url, "calendar_url")
        username, password = basic_auth_pair(
            *await load_credential(ctx.organization_id, config.get("credential_uuid"))
        )
        return CalDAVCalendar(url, username, password)
    if provider == "google":
        credential_type, data = await load_credential(
            ctx.organization_id, config.get("credential_uuid")
        )
        if credential_type != "service_account":
            raise ActionError("Google Calendar needs a service-account credential")
        try:
            info = json.loads(data.get("service_account_json") or "{}")
        except ValueError as exc:
            raise ActionError("The service-account JSON key is invalid") from exc
        return GoogleCalendar(config["calendar_id"], info)
    return NimboraCalendar(ctx.organization_id, ctx.tool_uuid)


async def rules_for(ctx: ActionContext, config: dict[str, Any]) -> SlotRules:
    if config.get("timezone"):
        tz = ZoneInfo(config["timezone"])
    else:
        from api.services.contact_center.callbacks import organization_timezone

        tz = await organization_timezone(ctx.organization_id)
    from api.schemas.tool import BookAppointmentConfig

    defaults = BookAppointmentConfig()
    return SlotRules(
        tz=tz,
        opening_hours=config.get("opening_hours") or defaults.opening_hours,
        slot_minutes=int(config.get("slot_minutes") or defaults.slot_minutes),
        buffer_minutes=int(config.get("buffer_minutes") or 0),
        min_notice_minutes=int(
            config.get("min_notice_minutes")
            if config.get("min_notice_minutes") is not None
            else defaults.min_notice_minutes
        ),
        horizon_days=int(config.get("horizon_days") or defaults.horizon_days),
    )


async def _busy(
    backend, ctx: ActionContext, start: datetime, end: datetime
) -> list[Interval]:
    busy = await backend.busy(start, end)
    if not isinstance(backend, NimboraCalendar):
        # Bookings made a second ago may not be visible remotely yet.
        busy += await NimboraCalendar(ctx.organization_id, ctx.tool_uuid).busy(
            start, end
        )
    return busy


def _parse_local(value: Any, tz: ZoneInfo) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ActionError(
            "start must be an ISO date-time such as 2026-11-25T10:30"
        ) from exc
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed


def _slot_payload(slot: Interval, tz: ZoneInfo) -> dict[str, str]:
    return {
        "start": slot.start.astimezone(tz).strftime("%Y-%m-%dT%H:%M"),
        "label": describe_slot(slot, tz),
    }


async def find_slots(ctx, config, args, backend, rules) -> dict[str, Any]:
    tz = rules.tz
    after = str(args.get("after_time") or "").strip()
    if args.get("date"):
        try:
            day = date.fromisoformat(str(args["date"])[:10])
        except ValueError as exc:
            raise ActionError("date must be YYYY-MM-DD") from exc
        days = [day]
    else:
        days = next_open_days(rules, now=ctx.now, count=10)
    if not days:
        return {"status": "no_slots", "message": "No opening hours are configured."}
    start, _ = day_bounds(days[0], tz)
    _, end = day_bounds(days[-1], tz)
    busy = await _busy(backend, ctx, start, end)
    slots: list[Interval] = []
    for day in days:
        found = free_slots(rules, busy, now=ctx.now, start_day=day, days=1, limit=24)
        if after:
            found = [
                s for s in found if s.start.astimezone(tz).strftime("%H:%M") >= after
            ]
        # Spread the offer: a few slots per day, over a few days.
        slots += found[: 3 if len(days) > 1 else 8]
        if len(slots) >= 6:
            break
    if not slots:
        return {
            "status": "no_slots",
            "message": "No free slot on that day. Offer another day.",
        }
    return {
        "status": "ok",
        "timezone": str(tz),
        "slots": [_slot_payload(s, tz) for s in slots[:6]],
        "instructions": (
            "Offer two or three of these slots by their label, then call this tool "
            "with action=book and the chosen start."
        ),
    }


async def book(ctx, config, args, backend, rules) -> dict[str, Any]:
    from api.db import db_client
    from api.services.customer_memory.service import normalize_phone

    tz = rules.tz
    if not args.get("start"):
        raise ActionError("start is required to book")
    start = _parse_local(args["start"], tz)
    slot = Interval(start, start + timedelta(minutes=rules.slot_minutes))
    busy = await _busy(
        backend, ctx, slot.start - timedelta(hours=1), slot.end + timedelta(hours=1)
    )
    refusal = is_bookable(rules, slot, busy, now=ctx.now)
    if refusal:
        return {
            "status": "unavailable",
            "reason": refusal,
            "message": REFUSALS[refusal],
        }

    name = str(args.get("name") or ctx.customer_name or "").strip()[:128] or None
    phone = normalize_phone(args.get("phone")) or ctx.caller_phone
    email = str(args.get("email") or "").strip()[:255] or None
    reason = str(args.get("reason") or "").strip()[:1000] or None
    summary = f"Rendez-vous — {name or phone or 'client'}"
    description = "\n".join(
        line
        for line in (
            f"Motif : {reason}" if reason else "",
            f"Téléphone : {phone}" if phone else "",
            f"E-mail : {email}" if email else "",
            "Réservé par un agent NIMBORA.",
        )
        if line
    )
    external_id = await backend.create(slot, summary=summary, description=description)
    appointment = await db_client.create_appointment(
        organization_id=ctx.organization_id,
        calendar_key=ctx.tool_uuid,
        calendar_name=config.get("calendar_name") or ctx.tool_name,
        provider=config.get("provider") or "nimbora",
        external_id=external_id,
        start_at=slot.start.astimezone(UTC),
        end_at=slot.end.astimezone(UTC),
        customer_name=name,
        phone=phone,
        email=email,
        reason=reason,
        status="booked",
        workflow_run_id=ctx.workflow_run_id,
    )
    # Two calls may book the same slot at the same second: the later one yields.
    competing = [
        a
        for a in await db_client.list_booked_appointments_between(
            ctx.organization_id, ctx.tool_uuid, slot.start, slot.end
        )
        if a.id != appointment.id
    ]
    if any(a.id < appointment.id for a in competing):
        await db_client.cancel_appointment(ctx.organization_id, appointment.id)
        if external_id:
            try:
                await backend.delete(external_id)
            except CalendarError:
                logger.warning("Could not remove a double booking from the calendar")
        return {
            "status": "unavailable",
            "reason": "taken",
            "message": REFUSALS["taken"],
        }
    return {
        "status": "booked",
        "appointment_id": appointment.id,
        "when": describe_slot(slot, tz),
        "duration_minutes": rules.slot_minutes,
        "message": "Confirm the date and time to the caller.",
    }


async def my_appointments(ctx, config, args, backend, rules) -> dict[str, Any]:
    from api.db import db_client

    phone = ctx.caller_phone
    if not phone:
        return {"status": "unknown_caller", "appointments": []}
    rows = [
        a
        for a in await db_client.list_appointments(
            ctx.organization_id, start=ctx.now, phone=phone, status="booked"
        )
        if a.calendar_key == ctx.tool_uuid
    ]
    return {
        "status": "ok",
        "appointments": [
            {
                "appointment_id": a.id,
                "when": describe_slot(Interval(a.start_at, a.end_at), rules.tz),
                "reason": a.reason,
            }
            for a in rows[:5]
        ],
    }


async def cancel(ctx, config, args, backend, rules) -> dict[str, Any]:
    from api.db import db_client

    if config.get("allow_cancel") is False:
        return {
            "status": "not_allowed",
            "message": "Cancellations are not handled by phone.",
        }
    phone = ctx.caller_phone
    appointment = None
    if args.get("appointment_id"):
        appointment = await db_client.get_appointment(
            ctx.organization_id, int(args["appointment_id"])
        )
    elif phone:
        upcoming = (await my_appointments(ctx, config, args, backend, rules))[
            "appointments"
        ]
        if len(upcoming) == 1:
            appointment = await db_client.get_appointment(
                ctx.organization_id, upcoming[0]["appointment_id"]
            )
        elif upcoming:
            return {
                "status": "ambiguous",
                "appointments": upcoming,
                "message": "Ask which appointment to cancel, then pass its appointment_id.",
            }
    # Callers cancel only their own appointments.
    if (
        appointment is None
        or appointment.calendar_key != ctx.tool_uuid
        or appointment.status != "booked"
        or not phone
        or appointment.phone != phone
    ):
        return {
            "status": "not_found",
            "message": "No upcoming appointment found for this caller.",
        }
    if appointment.external_id:
        await backend.delete(appointment.external_id)
    await db_client.cancel_appointment(ctx.organization_id, appointment.id)
    return {
        "status": "canceled",
        "when": describe_slot(
            Interval(appointment.start_at, appointment.end_at), rules.tz
        ),
    }


ACTIONS = {
    "find_slots": find_slots,
    "book": book,
    "my_appointments": my_appointments,
    "cancel": cancel,
}


async def handle_calendar(
    ctx: ActionContext, config: dict[str, Any], args: dict[str, Any]
):
    action = str(args.get("action") or "find_slots")
    handler = ACTIONS.get(action)
    if handler is None:
        raise ActionError(f"Unknown action '{action}'")
    rules = await rules_for(ctx, config)
    backend = await build_backend(ctx, config)
    try:
        return await handler(ctx, config, args, backend, rules)
    except CalendarError as exc:
        raise ActionError(f"The calendar is unavailable: {exc}") from exc

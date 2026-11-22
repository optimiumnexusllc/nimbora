"""AI Business Hub: one view of what the agents and the team did.

Conversations by channel (phone, WhatsApp, web), AI and human calls, hand-offs,
appointments, messages, tickets, callbacks, customers and leads, compared with
the period before, and a day-by-day activity per channel.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from api.services.catalog.service import format_price

PHONE_MODES = {
    "ari",
    "plivo",
    "twilio",
    "vonage",
    "vobiz",
    "cloudonix",
    "exotel",
    "telnyx",
}
WEB_MODES = {"webrtc", "smallwebrtc", "textchat"}
CHANNELS = ("phone", "whatsapp", "web")
CHANNEL_LABELS = {"phone": "Téléphone", "whatsapp": "WhatsApp", "web": "Web"}
PERIODS = {"7d": 7, "30d": 30, "90d": 90}


def channel_of(mode: str | None) -> str:
    mode = (mode or "").lower()
    if mode == "whatsapp":
        return "whatsapp"
    if mode in WEB_MODES:
        return "web"
    return "phone"


def change(current: float, previous: float) -> float | None:
    """Percentage change; None when there was nothing before."""
    if not previous:
        return None
    return round((current - previous) * 100 / previous, 1)


def _zone(name: str | None) -> str:
    try:
        ZoneInfo(name or "UTC")
        return name or "UTC"
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"


def period_bounds(
    period: str, now: datetime, tz: str
) -> tuple[datetime, datetime, datetime, list[str]]:
    """[start, end) ending tonight at midnight in the company's zone, the
    previous period's start, and the days of the period."""
    days = PERIODS.get(period, 30)
    zone = ZoneInfo(tz)
    local_now = now.astimezone(zone)
    end_local = (local_now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_local = end_local - timedelta(days=days)
    labels = [
        (start_local + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)
    ]
    start = start_local.astimezone(UTC)
    return start, end_local.astimezone(UTC), start - timedelta(days=days), labels


async def _ai(organization_id: int, start, end, tz) -> dict[str, Any]:
    from api.db import db_client

    rows = await db_client.hub_ai_runs(organization_id, start, end, tz)
    per_channel = {c: {"count": 0, "seconds": 0.0} for c in CHANNELS}
    inbound = outbound = 0
    for r in rows:
        bucket = per_channel[channel_of(r["mode"])]
        bucket["count"] += r["count"]
        bucket["seconds"] += r["seconds"]
        if channel_of(r["mode"]) == "phone":
            if r["direction"] == "inbound":
                inbound += r["count"]
            else:
                outbound += r["count"]
    return {
        "rows": rows,
        "per_channel": per_channel,
        "inbound": inbound,
        "outbound": outbound,
    }


async def business_hub(
    organization_id: int, period: str = "30d", now: datetime | None = None
) -> dict[str, Any]:
    from api.db import db_client
    from api.services.business.profile import get_business_profile

    now = now or datetime.now(UTC)
    profile = await get_business_profile(organization_id)
    tz = _zone(getattr(profile, "timezone", None))
    start, end, previous_start, days = period_bounds(period, now, tz)

    ai, ai_before = (
        await _ai(organization_id, start, end, tz),
        await _ai(organization_id, previous_start, start, tz),
    )
    human = await db_client.hub_human_calls(organization_id, start, end, tz)
    human_before = await db_client.hub_human_calls(
        organization_id, previous_start, start, tz
    )
    counts = await db_client.hub_counts(organization_id, start, end, now)
    before = await db_client.hub_counts(organization_id, previous_start, start, now)
    events = await db_client.hub_daily_events(organization_id, start, end, tz)
    pipeline = await db_client.hub_open_pipeline(organization_id)

    human_calls = sum(r["count"] for r in human)
    human_minutes = round(sum(r["seconds"] for r in human) / 60)
    ai_calls = ai["per_channel"]["phone"]["count"]
    # A WhatsApp conversation is one row; AI runs on WhatsApp are its turns.
    conversations = {
        "phone": ai_calls + human_calls,
        "whatsapp": counts["whatsapp_conversations"],
        "web": ai["per_channel"]["web"]["count"],
    }
    conversations_before = {
        "phone": ai_before["per_channel"]["phone"]["count"]
        + sum(r["count"] for r in human_before),
        "whatsapp": before["whatsapp_conversations"],
        "web": ai_before["per_channel"]["web"]["count"],
    }
    total = sum(conversations.values())
    total_before = sum(conversations_before.values())

    # Day by day, per channel.
    daily = {
        d: {
            "day": d,
            "phone_ai": 0,
            "phone_human": 0,
            "whatsapp": 0,
            "web": 0,
            "appointments": 0,
            "leads": 0,
        }
        for d in days
    }
    for r in ai["rows"]:
        channel = channel_of(r["mode"])
        if r["day"] in daily and channel != "whatsapp":
            daily[r["day"]]["phone_ai" if channel == "phone" else "web"] += r["count"]
    for r in human:
        if r["day"] in daily:
            daily[r["day"]]["phone_human"] += r["count"]
    for e in events:
        if e["day"] in daily:
            daily[e["day"]][e["source"]] += e["count"]

    def kpi(value: float, previous: float, **extra) -> dict[str, Any]:
        return {
            "value": value,
            "previous": previous,
            "change": change(value, previous),
            **extra,
        }

    handoff_rate = round(counts["handoffs"] * 100 / ai_calls, 1) if ai_calls else None
    conversion = (
        round(counts["leads_won"] * 100 / counts["leads_new"], 1)
        if counts["leads_new"]
        else None
    )
    return {
        "period": period if period in PERIODS else "30d",
        "timezone": tz,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "kpis": {
            "conversations": kpi(total, total_before),
            "ai_calls": kpi(
                ai_calls,
                ai_before["per_channel"]["phone"]["count"],
                inbound=ai["inbound"],
                outbound=ai["outbound"],
                minutes=round(ai["per_channel"]["phone"]["seconds"] / 60),
            ),
            "human_calls": kpi(
                human_calls,
                sum(r["count"] for r in human_before),
                minutes=human_minutes,
            ),
            "appointments": kpi(
                counts["appointments_booked"],
                before["appointments_booked"],
                upcoming=counts["appointments_upcoming"],
                canceled=counts["appointments_canceled"],
            ),
            "leads": kpi(
                counts["leads_new"],
                before["leads_new"],
                qualified=counts["leads_qualified"],
                won=counts["leads_won"],
                lost=counts["leads_lost"],
                conversion=conversion,
            ),
            "customers": kpi(counts["customers_new"], before["customers_new"]),
        },
        "channels": [
            {
                "channel": c,
                "label": CHANNEL_LABELS[c],
                "count": conversations[c],
                "previous": conversations_before[c],
                "share": round(conversations[c] * 100 / total, 1) if total else 0,
            }
            for c in CHANNELS
        ],
        "actions": {
            "handoffs": counts["handoffs"],
            "handoffs_answered": counts["handoffs_answered"],
            "handoff_rate": handoff_rate,
            "messages_sent": counts["messages_sent"],
            "tickets_created": counts["tickets_created"],
            "tickets_open": counts["tickets_open"],
            "callbacks_created": counts["callbacks_created"],
            "callbacks_done": counts["callbacks_done"],
            "whatsapp_messages": counts["whatsapp_messages"],
        },
        "pipeline": [
            {
                "currency": p["currency"],
                "open_leads": p["open"],
                "budget": p["budget"],
                "text": format_price(p["budget"], p["currency"]),
            }
            for p in pipeline
            if p["open"]
        ],
        "daily": list(daily.values()),
    }

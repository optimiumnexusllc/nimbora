"""Free appointment slots: opening hours minus busy time.

Pure functions, timezone-aware: opening hours are read in the calendar's
time zone (so a DST change never shifts "09:00"), busy intervals and results
are aware datetimes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

FRENCH_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class SlotRules:
    tz: ZoneInfo
    opening_hours: dict[str, list[str]]
    slot_minutes: int = 30
    buffer_minutes: int = 0
    min_notice_minutes: int = 60
    horizon_days: int = 30


def _parse_range(value: str) -> tuple[time, time]:
    start, end = value.split("-")
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    return time(sh, sm), (time(23, 59, 59) if eh == 24 else time(eh, em))


def opening_intervals(day: date, rules: SlotRules) -> list[Interval]:
    ranges = rules.opening_hours.get(WEEKDAYS[day.weekday()], [])
    intervals = []
    for item in ranges:
        start, end = _parse_range(item)
        intervals.append(
            Interval(
                datetime.combine(day, start, tzinfo=rules.tz),
                datetime.combine(day, end, tzinfo=rules.tz),
            )
        )
    return intervals


def free_slots(
    rules: SlotRules,
    busy: Iterable[Interval],
    *,
    now: datetime,
    start_day: date | None = None,
    days: int = 1,
    limit: int = 8,
) -> list[Interval]:
    """Bookable slots from ``start_day`` for ``days`` days (capped by the horizon)."""
    busy = sorted(busy, key=lambda b: b.start)
    pad = timedelta(minutes=rules.buffer_minutes)
    length = timedelta(minutes=rules.slot_minutes)
    earliest = now + timedelta(minutes=rules.min_notice_minutes)
    latest = now + timedelta(days=rules.horizon_days)
    first = start_day or now.astimezone(rules.tz).date()
    slots: list[Interval] = []
    for offset in range(max(1, days)):
        day = first + timedelta(days=offset)
        for window in opening_intervals(day, rules):
            cursor = window.start
            while cursor + length <= window.end:
                slot = Interval(cursor, cursor + length)
                guarded = Interval(slot.start - pad, slot.end + pad)
                if (
                    slot.start >= earliest
                    and slot.start <= latest
                    and not any(guarded.overlaps(b) for b in busy)
                ):
                    slots.append(slot)
                    if len(slots) >= limit:
                        return slots
                cursor += length
    return slots


def is_bookable(
    rules: SlotRules, slot: Interval, busy: Iterable[Interval], *, now: datetime
) -> str | None:
    """None when ``slot`` can be booked, else the reason (for the agent)."""
    if slot.start < now + timedelta(minutes=rules.min_notice_minutes):
        return "too_soon"
    if slot.start > now + timedelta(days=rules.horizon_days):
        return "too_far"
    local_day = slot.start.astimezone(rules.tz).date()
    if not any(
        w.start <= slot.start and slot.end <= w.end
        for w in opening_intervals(local_day, rules)
    ):
        return "closed"
    pad = timedelta(minutes=rules.buffer_minutes)
    guarded = Interval(slot.start - pad, slot.end + pad)
    if any(guarded.overlaps(b) for b in busy):
        return "taken"
    return None


def describe_slot(slot: Interval, tz: ZoneInfo) -> str:
    """'mardi 25 novembre à 10h30' — what the agent can read out."""
    local = slot.start.astimezone(tz)
    minutes = f"{local.minute:02d}" if local.minute else ""
    return (
        f"{FRENCH_DAYS[local.weekday()]} {local.day} {FRENCH_MONTHS[local.month - 1]} "
        f"à {local.hour}h{minutes}"
    )


def next_open_days(rules: SlotRules, *, now: datetime, count: int = 14) -> list[date]:
    """Upcoming days with opening hours (to search slots without a date)."""
    days = []
    day = now.astimezone(rules.tz).date()
    for _ in range(rules.horizon_days + 1):
        if rules.opening_hours.get(WEEKDAYS[day.weekday()]):
            days.append(day)
            if len(days) >= count:
                break
        day += timedelta(days=1)
    return days

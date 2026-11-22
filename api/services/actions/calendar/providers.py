"""Calendar backends: NIMBORA's own agenda, CalDAV, Google Calendar.

Each backend answers three questions: what is busy between two instants,
book this interval, remove that booking. NIMBORA keeps a row for every
booking whatever the backend (``appointments``), which is how agents cancel
and how the team sees what was booked.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx

from api.services.actions.calendar.slots import Interval

TIMEOUT = httpx.Timeout(10.0)


class CalendarError(RuntimeError):
    """A calendar that cannot be reached or refuses the operation."""


class CalendarBackend(Protocol):
    async def busy(self, start: datetime, end: datetime) -> list[Interval]: ...

    async def create(
        self, slot: Interval, *, summary: str, description: str
    ) -> str | None: ...

    async def delete(self, external_id: str) -> None: ...


class NimboraCalendar:
    """Bookings live only in NIMBORA (busy time = booked appointments)."""

    def __init__(self, organization_id: int, calendar_key: str):
        self.organization_id = organization_id
        self.calendar_key = calendar_key

    async def busy(self, start: datetime, end: datetime) -> list[Interval]:
        from api.db import db_client

        rows = await db_client.list_booked_appointments_between(
            self.organization_id, self.calendar_key, start, end
        )
        return [Interval(r.start_at, r.end_at) for r in rows]

    async def create(
        self, slot: Interval, *, summary: str, description: str
    ) -> str | None:
        return None

    async def delete(self, external_id: str) -> None:
        return None


# -------------------------------------------------------------------- iCal


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _parse_ical_datetime(name_params: str, value: str) -> datetime:
    params = dict(
        part.split("=", 1) for part in name_params.split(";")[1:] if "=" in part
    )
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        day = datetime.strptime(value[:8], "%Y%m%d")
        tz = ZoneInfo(params["TZID"]) if "TZID" in params else UTC
        return day.replace(tzinfo=tz)
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    tz = ZoneInfo(params["TZID"]) if "TZID" in params else UTC
    return naive.replace(tzinfo=tz)


_DURATION_RE = re.compile(
    r"^P(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$"
)


def _parse_duration(value: str) -> timedelta:
    match = _DURATION_RE.match(value.strip())
    if not match:
        return timedelta(0)
    parts = {k: int(v) for k, v in match.groupdict().items() if v}
    return timedelta(
        weeks=parts.get("w", 0),
        days=parts.get("d", 0),
        hours=parts.get("h", 0),
        minutes=parts.get("m", 0),
        seconds=parts.get("s", 0),
    )


def parse_busy_events(ical: str) -> list[Interval]:
    """Busy intervals of the VEVENTs in an iCalendar text.

    Transparent ("free") and cancelled events do not block a slot.
    """
    intervals: list[Interval] = []
    event: dict[str, tuple[str, str]] | None = None
    for line in _unfold(ical):
        if line == "BEGIN:VEVENT":
            event = {}
            continue
        if line == "END:VEVENT" and event is not None:
            if (
                "DTSTART" in event
                and event.get("TRANSP", ("", ""))[1].upper() != "TRANSPARENT"
                and event.get("STATUS", ("", ""))[1].upper() != "CANCELLED"
            ):
                start = _parse_ical_datetime(*event["DTSTART"])
                if "DTEND" in event:
                    end = _parse_ical_datetime(*event["DTEND"])
                elif "DURATION" in event:
                    end = start + _parse_duration(event["DURATION"][1])
                elif "VALUE=DATE" in event["DTSTART"][0]:
                    end = start + timedelta(days=1)
                else:
                    end = start
                if end > start:
                    intervals.append(Interval(start, end))
            event = None
            continue
        if event is not None and ":" in line:
            name_params, value = line.split(":", 1)
            name = name_params.split(";", 1)[0].upper()
            if name in {"DTSTART", "DTEND", "DURATION", "TRANSP", "STATUS"}:
                event[name] = (name_params, value)
    return intervals


def _ical_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_event_ical(
    uid: str, slot: Interval, *, summary: str, description: str
) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    fmt = "%Y%m%dT%H%M%SZ"
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//NIMBORA//Agent booking//FR",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{slot.start.astimezone(UTC).strftime(fmt)}",
            f"DTEND:{slot.end.astimezone(UTC).strftime(fmt)}",
            f"SUMMARY:{_ical_escape(summary)}",
            f"DESCRIPTION:{_ical_escape(description)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


# ------------------------------------------------------------------ CalDAV

_CALDAV_NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}


class CalDAVCalendar:
    def __init__(self, calendar_url: str, username: str, password: str, transport=None):
        self.url = calendar_url.rstrip("/") + "/"
        self.auth = httpx.BasicAuth(username, password)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            auth=self.auth,
            timeout=TIMEOUT,
            transport=self._transport,
            follow_redirects=False,
        )

    async def busy(self, start: datetime, end: datetime) -> list[Interval]:
        fmt = "%Y%m%dT%H%M%SZ"
        span = (
            f'start="{start.astimezone(UTC).strftime(fmt)}" '
            f'end="{end.astimezone(UTC).strftime(fmt)}"'
        )
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f"<d:prop><c:calendar-data><c:expand {span}/></c:calendar-data></d:prop>"
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            f"<c:time-range {span}/>"
            "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
        )
        async with self._client() as client:
            response = await client.request(
                "REPORT",
                self.url,
                content=body.encode(),
                headers={
                    "Depth": "1",
                    "Content-Type": "application/xml; charset=utf-8",
                },
            )
        if response.status_code == 401:
            raise CalendarError("CalDAV login refused")
        if response.status_code not in (200, 207):
            raise CalendarError(f"CalDAV answered {response.status_code}")
        try:
            tree = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise CalendarError("Unreadable CalDAV response") from exc
        intervals: list[Interval] = []
        for data in tree.iter(f"{{{_CALDAV_NS['c']}}}calendar-data"):
            intervals.extend(parse_busy_events(data.text or ""))
        return intervals

    async def create(
        self, slot: Interval, *, summary: str, description: str
    ) -> str | None:
        uid = f"{uuid.uuid4()}@nimbora"
        href = f"{self.url}{uid.split('@')[0]}.ics"
        async with self._client() as client:
            response = await client.put(
                href,
                content=build_event_ical(
                    uid, slot, summary=summary, description=description
                ).encode(),
                headers={
                    "Content-Type": "text/calendar; charset=utf-8",
                    "If-None-Match": "*",
                },
            )
        if response.status_code not in (200, 201, 204):
            raise CalendarError(f"CalDAV refused the booking ({response.status_code})")
        return href

    async def delete(self, external_id: str) -> None:
        if not external_id.startswith(self.url):
            raise CalendarError("This booking does not belong to this calendar")
        async with self._client() as client:
            response = await client.delete(external_id)
        if response.status_code not in (200, 204, 404):
            raise CalendarError(
                f"CalDAV refused the cancellation ({response.status_code})"
            )


# ------------------------------------------------------------------ Google

GOOGLE_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar"


class GoogleCalendar:
    """Service account with the calendar shared to it ("make changes")."""

    def __init__(
        self, calendar_id: str, service_account_info: dict[str, Any], transport=None
    ):
        self.calendar_id = calendar_id
        self.info = service_account_info
        self._transport = transport
        self._token: str | None = None

    async def _access_token(self) -> str:
        if self._token:
            return self._token
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        def fetch() -> str:
            credentials = service_account.Credentials.from_service_account_info(
                self.info, scopes=[GOOGLE_SCOPE]
            )
            credentials.refresh(Request())
            return credentials.token

        try:
            self._token = await asyncio.to_thread(fetch)
        except Exception as exc:
            raise CalendarError("Google refused the service account") from exc
        return self._token

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        token = await self._access_token()
        async with httpx.AsyncClient(
            timeout=TIMEOUT, transport=self._transport
        ) as client:
            response = await client.request(
                method,
                f"{GOOGLE_API}{path}",
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
        if response.status_code in (401, 403):
            raise CalendarError("The calendar is not shared with the service account")
        return response

    async def busy(self, start: datetime, end: datetime) -> list[Interval]:
        response = await self._request(
            "POST",
            "/freeBusy",
            json={
                "timeMin": start.astimezone(UTC).isoformat(),
                "timeMax": end.astimezone(UTC).isoformat(),
                "items": [{"id": self.calendar_id}],
            },
        )
        if response.status_code != 200:
            raise CalendarError(f"Google Calendar answered {response.status_code}")
        calendar = (response.json().get("calendars") or {}).get(self.calendar_id) or {}
        if calendar.get("errors"):
            raise CalendarError("Google Calendar cannot read this calendar")
        return [
            Interval(
                datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
                datetime.fromisoformat(b["end"].replace("Z", "+00:00")),
            )
            for b in calendar.get("busy") or []
        ]

    async def create(
        self, slot: Interval, *, summary: str, description: str
    ) -> str | None:
        response = await self._request(
            "POST",
            f"/calendars/{_quote(self.calendar_id)}/events",
            json={
                "summary": summary,
                "description": description,
                "start": {"dateTime": slot.start.astimezone(UTC).isoformat()},
                "end": {"dateTime": slot.end.astimezone(UTC).isoformat()},
            },
        )
        if response.status_code not in (200, 201):
            raise CalendarError(
                f"Google Calendar refused the booking ({response.status_code})"
            )
        return response.json().get("id")

    async def delete(self, external_id: str) -> None:
        response = await self._request(
            "DELETE",
            f"/calendars/{_quote(self.calendar_id)}/events/{_quote(external_id)}",
        )
        if response.status_code not in (200, 204, 404, 410):
            raise CalendarError(
                f"Google Calendar refused the cancellation ({response.status_code})"
            )


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    return start, start + timedelta(days=1)

"""Agent actions: calendar (slots, CalDAV, Google), messages, tickets."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from api.services.actions import messaging, tickets
from api.services.actions.calendar import providers
from api.services.actions.calendar import service as calendar_service
from api.services.actions.calendar.slots import (
    Interval,
    SlotRules,
    describe_slot,
    free_slots,
    is_bookable,
)
from api.services.actions.common import ActionContext, ActionError, render_template
from api.services.actions.dispatch import run_action

PARIS = ZoneInfo("Europe/Paris")
# Thursday 20 Nov 2026, 08:00 Paris.
NOW = datetime(2026, 11, 20, 7, 0, tzinfo=UTC)
HOURS = {d: ["09:00-12:00", "14:00-17:00"] for d in ("mon", "tue", "wed", "thu", "fri")}


def _rules(**kw) -> SlotRules:
    return SlotRules(tz=PARIS, opening_hours=HOURS, **{"min_notice_minutes": 60, **kw})


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=PARIS)


# ------------------------------------------------------------------- slots


def test_free_slots_respect_hours_notice_busy_and_buffer():
    busy = [Interval(_at(20, 10, 0), _at(20, 11, 0))]
    slots = free_slots(
        _rules(buffer_minutes=15), busy, now=NOW, start_day=date(2026, 11, 20), limit=20
    )
    starts = [s.start.strftime("%H:%M") for s in slots]
    # 09:00 is within the 60-min notice (now 08:00) → first is 09:00? no: 09:00 >= 09:00 ok.
    assert starts[0] == "09:00"
    # 09:30 ends 10:00, +15 min buffer overlaps the 10:00 meeting; 11:00 too close after.
    assert "09:30" not in starts and "10:00" not in starts and "11:00" not in starts
    assert "11:30" in starts and "14:00" in starts and "16:30" in starts
    assert "12:00" not in starts and "17:00" not in starts
    # Weekend: nothing.
    assert free_slots(_rules(), [], now=NOW, start_day=date(2026, 11, 22)) == []


def test_is_bookable_reasons_and_french_labels():
    rules = _rules()
    ok = Interval(_at(24, 10), _at(24, 10, 30))
    assert is_bookable(rules, ok, [], now=NOW) is None
    assert (
        is_bookable(rules, Interval(_at(20, 8, 30), _at(20, 9)), [], now=NOW)
        == "too_soon"
    )
    assert (
        is_bookable(rules, Interval(_at(24, 12, 30), _at(24, 13)), [], now=NOW)
        == "closed"
    )
    assert (
        is_bookable(rules, ok, [Interval(_at(24, 10, 15), _at(24, 10, 45))], now=NOW)
        == "taken"
    )
    far = datetime(2027, 3, 1, 10, tzinfo=PARIS)
    assert (
        is_bookable(rules, Interval(far, far + timedelta(minutes=30)), [], now=NOW)
        == "too_far"
    )
    assert describe_slot(ok, PARIS) == "mardi 24 novembre à 10h"
    assert (
        describe_slot(Interval(_at(24, 14, 30), _at(24, 15)), PARIS)
        == "mardi 24 novembre à 14h30"
    )


def test_dst_keeps_local_opening_hours():
    # 29 March 2027: Paris switches to summer time; 09:00 stays 09:00 local.
    after_dst = datetime(2027, 3, 26, 7, 0, tzinfo=UTC)
    slots = free_slots(_rules(), [], now=after_dst, start_day=date(2027, 3, 29))
    assert slots[0].start.astimezone(PARIS).strftime("%H:%M") == "09:00"
    assert slots[0].start.astimezone(UTC).hour == 7


# -------------------------------------------------------------------- iCal

ICAL = (
    "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a\r\nDTSTART:20261124T090000Z\r\n"
    "DTEND:20261124T100000Z\r\nSUMMARY:Réunion\r\n  longue\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:b\r\nDTSTART;TZID=Europe/Paris:20261124T140000\r\n"
    "DURATION:PT45M\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:c\r\nDTSTART;VALUE=DATE:20261125\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:d\r\nDTSTART:20261126T090000Z\r\nDTEND:20261126T100000Z\r\n"
    "TRANSP:TRANSPARENT\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:e\r\nDTSTART:20261126T110000Z\r\nDTEND:20261126T120000Z\r\n"
    "STATUS:CANCELLED\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


def test_parse_busy_events():
    busy = providers.parse_busy_events(ICAL)
    assert [
        (b.start.isoformat(), (b.end - b.start).total_seconds() / 60) for b in busy
    ] == [
        ("2026-11-24T09:00:00+00:00", 60),
        ("2026-11-24T14:00:00+01:00", 45),
        ("2026-11-25T00:00:00+00:00", 1440),
    ]
    ical = providers.build_event_ical(
        "x@nimbora",
        Interval(_at(24, 10), _at(24, 10, 30)),
        summary="RDV; Awa",
        description="a\nb",
    )
    assert "DTSTART:20261124T090000Z" in ical and "SUMMARY:RDV\\; Awa" in ical


def _mock_client(monkeypatch, module, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


async def test_caldav_backend(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, str(request.url), request.headers.get("depth")))
        if request.method == "REPORT":
            assert b"<c:expand" in request.content
            body = (
                '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
                'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:propstat><d:prop>'
                f"<c:calendar-data>{ICAL}</c:calendar-data></d:prop></d:propstat>"
                "</d:response></d:multistatus>"
            )
            return httpx.Response(207, text=body)
        if request.method == "PUT":
            assert request.headers["if-none-match"] == "*"
            assert b"BEGIN:VEVENT" in request.content
            return httpx.Response(201)
        return httpx.Response(204)

    calendar = providers.CalDAVCalendar(
        "https://cloud.example.com/remote.php/dav/calendars/awa/rdv",
        "awa",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    busy = await calendar.busy(_at(24, 0), _at(27, 0))
    assert len(busy) == 3 and seen[0][2] == "1"
    href = await calendar.create(
        Interval(_at(24, 10), _at(24, 10, 30)), summary="RDV", description=""
    )
    assert href.startswith(
        "https://cloud.example.com/remote.php/dav/calendars/awa/rdv/"
    )
    await calendar.delete(href)
    with pytest.raises(providers.CalendarError):
        await calendar.delete("https://evil.example.com/x.ics")

    refused = providers.CalDAVCalendar(
        "https://cloud.example.com/cal",
        "awa",
        "bad",
        transport=httpx.MockTransport(lambda r: httpx.Response(401)),
    )
    with pytest.raises(providers.CalendarError, match="login"):
        await refused.busy(_at(24, 0), _at(25, 0))


async def test_google_backend():
    def handler(request: httpx.Request):
        assert request.headers["authorization"] == "Bearer tok"
        if request.url.path.endswith("/freeBusy"):
            return httpx.Response(
                200,
                json={
                    "calendars": {
                        "rdv@group.calendar.google.com": {
                            "busy": [
                                {
                                    "start": "2026-11-24T09:00:00Z",
                                    "end": "2026-11-24T10:00:00Z",
                                }
                            ]
                        }
                    }
                },
            )
        if request.method == "POST":
            assert "rdv%40group.calendar.google.com" in str(request.url)
            return httpx.Response(200, json={"id": "evt123"})
        return httpx.Response(204)

    calendar = providers.GoogleCalendar(
        "rdv@group.calendar.google.com", {}, transport=httpx.MockTransport(handler)
    )
    calendar._token = "tok"
    busy = await calendar.busy(_at(24, 0), _at(25, 0))
    assert busy[0].start == datetime(2026, 11, 24, 9, tzinfo=UTC)
    assert (
        await calendar.create(
            Interval(_at(24, 11), _at(24, 11, 30)), summary="x", description=""
        )
        == "evt123"
    )
    await calendar.delete("evt123")


def test_render_template():
    assert (
        render_template(
            "Bonjour {{customer_name}}, réf. {{ details }} {{missing}}!",
            {"customer_name": "Awa", "details": "NB-1"},
        )
        == "Bonjour Awa, réf. NB-1 !"
    )


# ------------------------------------------------------------- with the DB


async def _new_org(db):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    return user, org


def _ctx(org_id, *, phone="+33612345678", tool="cal-1", now=NOW, run=None):
    return ActionContext(
        organization_id=org_id,
        tool_uuid=tool,
        tool_name="Agenda",
        workflow_run_id=run,
        initial_context={"direction": "inbound", "caller_number": phone},
        gathered_context={"customer_name": "Awa Diallo"},
        now=now,
    )


CAL_CONFIG = {"provider": "nimbora", "timezone": "Europe/Paris", "opening_hours": HOURS}


async def test_nimbora_calendar_flow(db_session):
    _, org = await _new_org(db_session)
    ctx = _ctx(org.id)
    found = await run_action(
        "book_appointment",
        ctx,
        CAL_CONFIG,
        {"action": "find_slots", "date": "2026-11-24"},
    )
    assert found["status"] == "ok" and found["slots"][0] == {
        "start": "2026-11-24T09:00",
        "label": "mardi 24 novembre à 9h",
    }
    booked = await run_action(
        "book_appointment",
        ctx,
        CAL_CONFIG,
        {
            "action": "book",
            "start": "2026-11-24T09:00",
            "reason": "Ouverture de compte",
        },
    )
    assert booked["status"] == "booked" and booked["when"] == "mardi 24 novembre à 9h"
    stored = await db_session.get_appointment(org.id, booked["appointment_id"])
    assert stored.customer_name == "Awa Diallo" and stored.phone == "+33612345678"

    # The slot is gone for everyone; booking it again is refused.
    again = await run_action(
        "book_appointment",
        _ctx(org.id, phone="+22790000001"),
        CAL_CONFIG,
        {"action": "book", "start": "2026-11-24T09:00"},
    )
    assert again["status"] == "unavailable" and again["reason"] == "taken"
    refound = await run_action(
        "book_appointment",
        ctx,
        CAL_CONFIG,
        {"action": "find_slots", "date": "2026-11-24"},
    )
    assert refound["slots"][0]["start"] == "2026-11-24T09:30"
    closed = await run_action(
        "book_appointment",
        ctx,
        CAL_CONFIG,
        {"action": "book", "start": "2026-11-24T12:30"},
    )
    assert closed["reason"] == "closed"

    mine = await run_action(
        "book_appointment", ctx, CAL_CONFIG, {"action": "my_appointments"}
    )
    assert [a["appointment_id"] for a in mine["appointments"]] == [
        booked["appointment_id"]
    ]
    # Another caller cannot cancel it.
    other = await run_action(
        "book_appointment",
        _ctx(org.id, phone="+22790000001"),
        CAL_CONFIG,
        {"action": "cancel", "appointment_id": booked["appointment_id"]},
    )
    assert other["status"] == "not_found"
    canceled = await run_action(
        "book_appointment", ctx, CAL_CONFIG, {"action": "cancel"}
    )
    assert canceled["status"] == "canceled"
    assert (
        await db_session.get_appointment(org.id, booked["appointment_id"])
    ).status == "canceled"


async def test_simultaneous_booking_keeps_the_first(db_session):
    _, org = await _new_org(db_session)
    first = await db_session.create_appointment(
        organization_id=org.id,
        calendar_key="cal-1",
        provider="nimbora",
        start_at=_at(24, 10).astimezone(UTC),
        end_at=_at(24, 10, 30).astimezone(UTC),
        status="booked",
    )

    class Blind(providers.NimboraCalendar):
        async def busy(self, start, end):
            return []  # simulates the other call's booking not yet visible

    original = calendar_service.NimboraCalendar
    calendar_service.NimboraCalendar = Blind
    try:
        result = await calendar_service.book(
            _ctx(org.id),
            CAL_CONFIG,
            {"start": "2026-11-24T10:00"},
            Blind(org.id, "cal-1"),
            await calendar_service.rules_for(_ctx(org.id), CAL_CONFIG),
        )
    finally:
        calendar_service.NimboraCalendar = original
    assert result["status"] == "unavailable"
    booked = await db_session.list_booked_appointments_between(
        org.id, "cal-1", _at(24, 0), _at(25, 0)
    )
    assert [a.id for a in booked] == [first.id]


async def test_messages(db_session, monkeypatch):
    _, org = await _new_org(db_session)
    sent = []

    async def fake_twilio(config, credential, recipient, body):
        sent.append((recipient, body))
        return "SM123"

    async def fake_credential(org_id, uuid_):
        return "basic_auth", {"username": "AC1", "password": "tok"}

    monkeypatch.setattr(messaging, "send_twilio", fake_twilio)
    monkeypatch.setattr(messaging, "load_credential", fake_credential)
    config = {
        "channel": "sms",
        "provider": "twilio",
        "sender": "+33700000000",
        "credential_uuid": "c",
        "template": "Bonjour {{customer_name}}, voici le lien : {{details}}",
        "max_per_call": 2,
    }
    ctx = _ctx(org.id, tool="sms-1", run=None)
    result = await run_action(
        "send_message", ctx, config, {"message": "https://pay.example/1"}
    )
    assert result == {
        "status": "sent",
        "channel": "sms",
        "to": "…5678",
        "message": "Tell the caller the message was sent.",
    }
    assert sent == [
        ("+33612345678", "Bonjour Awa Diallo, voici le lien : https://pay.example/1")
    ]
    refused = await run_action(
        "send_message", ctx, config, {"message": "x", "to": "+22790000009"}
    )
    assert refused["status"] == "error" and "own number" in refused["error"]
    log = await db_session.list_sent_messages(org.id)
    assert log[0].status == "sent" and log[0].provider_message_id == "SM123"

    # Provider failure is logged as failed and explained to the agent.
    async def failing(*a):
        raise ActionError("Twilio refused the message (400) Invalid 'To'")

    monkeypatch.setattr(messaging, "send_twilio", failing)
    failed = await run_action("send_message", ctx, config, {"message": "x"})
    assert failed["status"] == "failed" and "Invalid" in failed["message"]

    # E-mail: address required and validated.
    email_config = {
        "channel": "email",
        "provider": "smtp",
        "sender": "rdv@acme.fr",
        "smtp_host": "smtp.acme.fr",
        "credential_uuid": "c",
        "subject": "Votre rendez-vous",
    }
    bad = await run_action(
        "send_message", ctx, email_config, {"message": "x", "email": "awa at gmail"}
    )
    assert bad["status"] == "error"
    mails = []
    monkeypatch.setattr(
        messaging, "_send_email_sync", lambda *a: mails.append(a) or "<id@acme.fr>"
    )
    ok = await run_action(
        "send_message",
        ctx,
        email_config,
        {"message": "Mardi 10h", "email": "awa@gmail.com"},
    )
    assert (
        ok["status"] == "sent"
        and mails[0][3] == "awa@gmail.com"
        and mails[0][4] == "Votre rendez-vous"
    )


async def test_message_limit_per_call(db_session, monkeypatch):
    user, org = await _new_org(db_session)
    workflow = await db_session.create_workflow(
        "A", {"nodes": [], "edges": []}, user.id, org.id
    )
    run = await db_session.create_workflow_run(
        name="WR",
        workflow_id=workflow.id,
        mode="twilio",
        user_id=user.id,
        organization_id=org.id,
    )

    async def fake_http(*a):
        return "gw-1"

    monkeypatch.setattr(messaging, "send_http", fake_http)
    config = {
        "channel": "sms",
        "provider": "http",
        "sender": "NIMBORA",
        "gateway_url": "https://sms.example.com/send",
        "max_per_call": 1,
    }
    ctx = _ctx(org.id, tool="sms-2", run=run.id)
    assert (await run_action("send_message", ctx, config, {"message": "a"}))[
        "status"
    ] == "sent"
    assert (await run_action("send_message", ctx, config, {"message": "b"}))[
        "status"
    ] == "limit_reached"


async def test_twilio_whatsapp_request(monkeypatch):
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["form"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(201, json={"sid": "SM9"})

    _mock_client(monkeypatch, messaging, handler)
    sid = await messaging.send_twilio(
        {"channel": "whatsapp", "sender": "+14155238886"},
        ("basic_auth", {"username": "AC42", "password": "t"}),
        "+33612345678",
        "Bonjour",
    )
    assert sid == "SM9" and "/Accounts/AC42/Messages.json" in captured["url"]
    assert captured["form"] == {
        "From": "whatsapp:+14155238886",
        "To": "whatsapp:+33612345678",
        "Body": "Bonjour",
    }


async def test_tickets_internal_and_followup(db_session):
    _, org = await _new_org(db_session)
    _, other_org = await _new_org(db_session)
    config = {"provider": "nimbora", "categories": ["facturation", "technique"]}
    ctx = _ctx(org.id, tool="tk")
    first = await run_action(
        "create_ticket",
        ctx,
        config,
        {
            "action": "create",
            "subject": "Double prélèvement",
            "description": "45 000 FCFA x2",
            "priority": "high",
            "category": "facturation",
        },
    )
    second = await run_action(
        "create_ticket",
        ctx,
        config,
        {"action": "create", "subject": "Box en panne", "category": "inconnu"},
    )
    assert (first["ticket_number"], second["ticket_number"]) == (1001, 1002)
    assert (
        await run_action(
            "create_ticket",
            _ctx(other_org.id),
            config,
            {"action": "create", "subject": "x"},
        )
    )["ticket_number"] == 1001
    stored = await db_session.get_ticket_by_number(org.id, 1002)
    assert stored.category is None and stored.priority == "normal"
    assert "Téléphone de l'appelant : +33612345678" in stored.description

    await db_session.update_ticket(
        org.id, stored.id, {"status": "solved", "resolution": "Box remplacée"}
    )
    lookup = await run_action(
        "create_ticket", ctx, config, {"action": "lookup", "ticket_number": "#1002"}
    )
    assert lookup["tickets"][0]["status_label"] == "résolu"
    assert lookup["tickets"][0]["resolution"] == "Box remplacée"
    # Someone else's ticket number reveals nothing.
    stranger = await run_action(
        "create_ticket",
        _ctx(org.id, phone="+22790000001"),
        config,
        {"action": "lookup", "ticket_number": "1001"},
    )
    assert stranger["status"] == "not_found"
    assert (await run_action("create_ticket", ctx, config, {"action": "create"}))[
        "status"
    ] == "error"


async def test_zendesk_and_freshdesk(db_session, monkeypatch):
    _, org = await _new_org(db_session)
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        host = request.url.host
        if request.method == "POST" and host.endswith("zendesk.com"):
            body = json.loads(request.content)
            assert (
                body["ticket"]["priority"] == "urgent"
                and "nimbora" in body["ticket"]["tags"]
            )
            return httpx.Response(201, json={"ticket": {"id": 77}})
        if request.method == "GET" and host.endswith("zendesk.com"):
            return httpx.Response(200, json={"ticket": {"status": "hold"}})
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["phone"] == "+33612345678" and body["priority"] == 2
            return httpx.Response(201, json={"id": 501})
        return httpx.Response(200, json={"status": 4})

    _mock_client(monkeypatch, tickets, handler)

    async def fake_credential(org_id, uuid_):
        return "basic_auth", {"username": "agent@acme.fr/token", "password": "tok"}

    monkeypatch.setattr(tickets, "load_credential", fake_credential)
    zendesk = {
        "provider": "zendesk",
        "domain": "acme.zendesk.com",
        "credential_uuid": "c",
    }
    ctx = _ctx(org.id, tool="zd")
    created = await run_action(
        "create_ticket",
        ctx,
        zendesk,
        {"action": "create", "subject": "Panne", "priority": "urgent"},
    )
    ticket = await db_session.get_ticket_by_number(org.id, created["ticket_number"])
    assert (
        ticket.external_id == "77"
        and ticket.external_url == "https://acme.zendesk.com/agent/tickets/77"
    )
    lookup = await run_action("create_ticket", ctx, zendesk, {"action": "lookup"})
    assert lookup["tickets"][0]["status"] == "pending"

    freshdesk = {
        "provider": "freshdesk",
        "domain": "acme.freshdesk.com",
        "credential_uuid": "c",
    }
    created = await run_action(
        "create_ticket", ctx, freshdesk, {"action": "create", "subject": "Facture"}
    )
    fd = await db_session.get_ticket_by_number(org.id, created["ticket_number"])
    assert fd.external_url == "https://acme.freshdesk.com/a/tickets/501"
    assert requests[-1].headers["authorization"].startswith("Basic ")


async def test_every_tool_type_can_be_saved(db_session, test_client_factory):
    """Regression: new categories must exist in the PostgreSQL enum."""
    user, org = await _new_org(db_session)
    credential = await db_session.create_credential(
        organization_id=org.id,
        name="Twilio",
        credential_type="basic_auth",
        credential_data={"username": "AC1", "password": "x"},
        user_id=user.id,
    )
    definitions = [
        {"type": "schedule_callback"},
        {"type": "book_appointment"},
        {"type": "create_ticket"},
        {
            "type": "send_message",
            "config": {
                "channel": "sms",
                "provider": "twilio",
                "sender": "+33700000000",
                "credential_uuid": credential.credential_uuid,
            },
        },
    ]
    async with test_client_factory(user) as client:
        for definition in definitions:
            response = await client.post(
                "/api/v1/tools/",
                json={"name": f"T {definition['type']}", "definition": definition},
            )
            assert response.status_code in (200, 201), response.text
        bad = await client.post(
            "/api/v1/tools/",
            json={
                "name": "x",
                "definition": {
                    "type": "send_message",
                    "config": {
                        "channel": "sms",
                        "provider": "twilio",
                        "sender": "+3",
                        "credential_uuid": str(uuid.uuid4()),
                    },
                },
            },
        )
        assert bad.status_code in (400, 404)
        sa_bad = await client.post(
            "/api/v1/credentials/",
            json={
                "name": "Google",
                "credential_type": "service_account",
                "credential_data": {"service_account_json": '{"type": "user"}'},
            },
        )
        assert sa_bad.status_code == 400
        sa_ok = await client.post(
            "/api/v1/credentials/",
            json={
                "name": "Google",
                "credential_type": "service_account",
                "credential_data": {
                    "service_account_json": json.dumps(
                        {"type": "service_account", "private_key": "k"}
                    )
                },
            },
        )
        assert sa_ok.status_code in (200, 201), sa_ok.text


async def test_activity_routes(db_session, test_client_factory):
    user, org = await _new_org(db_session)
    other, _ = await _new_org(db_session)
    async with test_client_factory(user) as client:
        created = await client.post(
            "/api/v1/tools/",
            json={
                "name": "Agenda",
                "definition": {"type": "book_appointment", "config": CAL_CONFIG},
            },
        )
        tool_uuid = created.json()["tool_uuid"]
        preview = (
            await client.post(f"/api/v1/actions/calendars/{tool_uuid}/preview")
        ).json()
        assert preview["status"] == "ok" and len(preview["slots"]) >= 1
        start = datetime.fromisoformat(preview["slots"][0]["start"]).replace(
            tzinfo=PARIS
        )
        appointment = await db_session.create_appointment(
            organization_id=org.id,
            calendar_key=tool_uuid,
            provider="nimbora",
            start_at=start.astimezone(UTC),
            end_at=(start + timedelta(minutes=30)).astimezone(UTC),
            status="booked",
            customer_name="Awa",
        )
        upcoming = (await client.get("/api/v1/actions/appointments")).json()
        assert [a["id"] for a in upcoming] == [appointment.id]
        canceled = await client.post(
            f"/api/v1/actions/appointments/{appointment.id}/cancel"
        )
        assert canceled.json()["status"] == "canceled"
        await run_action(
            "create_ticket",
            _ctx(org.id, tool="tk"),
            {"provider": "nimbora"},
            {"action": "create", "subject": "Panne"},
        )
        tickets_open = (await client.get("/api/v1/actions/tickets")).json()
        assert tickets_open[0]["number"] == 1001
        solved = await client.patch(
            f"/api/v1/actions/tickets/{tickets_open[0]['id']}",
            json={"status": "solved", "resolution": "OK"},
        )
        assert solved.json()["status"] == "solved"
        assert (await client.get("/api/v1/actions/tickets")).json() == []
        summary = (await client.get("/api/v1/actions/summary")).json()
        assert summary == {
            "upcoming_appointments": 0,
            "messages_today": 0,
            "open_tickets": 0,
        }
    async with test_client_factory(other) as client:
        assert (await client.get("/api/v1/actions/tickets?view=all")).json() == []
        assert (
            await client.post(f"/api/v1/actions/appointments/{appointment.id}/cancel")
        ).status_code == 404
        assert (
            await client.post(f"/api/v1/actions/calendars/{tool_uuid}/preview")
        ).status_code == 404


async def test_unconfigured_message_tool_explains_itself(db_session):
    _, org = await _new_org(db_session)
    result = await run_action(
        "send_message",
        _ctx(org.id, tool="sms-x"),
        {"channel": "sms", "provider": "twilio"},
        {"message": "x"},
    )
    assert result["status"] == "error" and "sender, credential" in result["error"]
    assert await db_session.list_sent_messages(org.id) == []

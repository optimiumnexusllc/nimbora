"""Supervision of the enterprise PBX: live queues (AMI QueueStatus), agents and
conversations, listening sessions through calld + ChanSpy, statistics."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from api.services.pbx import client as client_module
from api.services.pbx import service as pbx
from api.services.pbx import supervision
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"
DIALPLAN = (
    Path(__file__).resolve().parents[2]
    / "deploy/pbx/templates/nimbora-supervision.conf"
)


@pytest.fixture(autouse=True)
def _clear():
    client_module._TOKENS.clear()
    supervision._live_cache.clear()
    yield
    supervision._live_cache.clear()


async def _setup(db, monkeypatch, fake, *, email=None):
    user = await db.create_user_with_email(
        email=email or f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    install(monkeypatch, fake)
    await db.save_pbx_connection(
        org.id,
        {
            "base_url": BASE,
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    return user, org


def test_queue_status_parsing_keeps_only_the_named_queue():
    messages = [
        {"Response": "Success", "EventList": "start"},
        {"Event": "QueueParams", "Queue": "ventes", "Calls": "2"},
        {
            "Event": "QueueEntry",
            "Queue": "ventes",
            "Position": "2",
            "Wait": "5",
            "CallerIDNum": "<unknown>",
            "CallerIDName": "<unknown>",
        },
        {
            "Event": "QueueEntry",
            "Queue": "ventes",
            "Position": "1",
            "Wait": "61",
            "CallerIDNum": "+2250102030405",
            "CallerIDName": "Ibrahim",
        },
        # Another tenant's queue on a shared engine: never shown.
        {
            "Event": "QueueEntry",
            "Queue": "autre-client",
            "Position": "1",
            "Wait": "9",
            "CallerIDNum": "+33600000000",
        },
        {
            "Event": "QueueMember",
            "Queue": "ventes",
            "Name": "Agent/1001",
            "InCall": "1",
            "Paused": "0",
            "CallsTaken": "3",
        },
        {"Event": "QueueStatusComplete", "EventList": "Complete"},
    ]
    parsed = supervision.parse_queue_status(messages, "ventes")
    assert [w["wait_seconds"] for w in parsed["waiting"]] == [61, 5]
    assert parsed["waiting"][1]["number"] is None  # masked caller
    assert parsed["members"] == [
        {"name": "Agent/1001", "in_call": True, "paused": False, "calls_taken": 3}
    ]


async def test_live_state(db_session, monkeypatch):
    fake = FakePbx()
    fake.statuses[0]["paused"] = False
    _, org = await _setup(db_session, monkeypatch, fake)
    live = await supervision.live(org.id)

    queue = live["queues"][0]
    assert queue["name"] == "Ventes" and queue["number"] == "3001" and queue["live"]
    assert queue["waiting"] == 1 and queue["longest_wait_seconds"] == 42
    assert queue["callers"][0]["name"] == "Ibrahim Touré"
    assert queue["agents_on_call"] == 1 and queue["agents_available"] == 0

    agent = live["agents"][0]
    assert agent["state"] == "on_call" and agent["user_uuid"] == "u-1"
    assert agent["call"]["with_number"] == "+2250700112233"
    assert agent["call"]["seconds"] > 0

    call = live["calls"][0]
    assert call["user_name"] == "Koffi Yao" and call["extension"] == "1001"
    assert call["spyable"] is False  # listening is off by default
    assert live["kpis"]["waiting"] == 1 and live["kpis"]["calls"] == 1
    assert live["errors"] == {}
    # The AMI is always asked about one named queue of the tenant.
    asked = [r for r in fake.requests if r[1].endswith("/action/QueueStatus")]
    assert len(asked) == 1

    # Cached for a moment: many supervisors, one PBX poll.
    await supervision.live(org.id)
    assert len([r for r in fake.requests if r[1].endswith("/action/QueueStatus")]) == 1


async def test_live_state_degrades_per_section(db_session, monkeypatch):
    fake = FakePbx()
    fake.down.add("amid")
    _, org = await _setup(db_session, monkeypatch, fake)
    live = await supervision.live(org.id, use_cache=False)
    assert live["queues"][0]["live"] is False and live["queues"][0]["waiting"] == 0
    assert "waiting" in live["errors"]
    assert live["agents"][0]["state"] == "on_call"  # the rest still works

    fake.down = {"agentd"}
    live = await supervision.live(org.id, use_cache=False)
    assert (
        live["agents"][0]["state"] == "logged_out"
        and "agent_statuses" in live["errors"]
    )


async def test_listening_is_opt_in_restricted_and_logged(db_session, monkeypatch):
    fake = FakePbx()
    user, org = await _setup(db_session, monkeypatch, fake)

    async def spy(supervisor="u-2", target="u-1", mode="listen"):
        return await supervision.start_spy(
            org.id,
            supervisor_user_uuid=supervisor,
            target_user_uuid=target,
            mode=mode,
            requested_by_user_id=user.id,
        )

    with pytest.raises(pbx.PbxRouteError) as off:
        await spy()
    assert off.value.status == 409 and not fake.originated

    # Enabling requires confirming that staff were informed.
    with pytest.raises(pbx.PbxRouteError) as notice:
        await supervision.save_settings(org.id, {"enabled": True})
    assert notice.value.status == 422
    with pytest.raises(pbx.PbxRouteError):
        await supervision.save_settings(
            org.id,
            {"enabled": True, "notice_acknowledged": True, "supervisors": ["nope"]},
        )
    settings = await supervision.save_settings(
        org.id,
        {"enabled": True, "notice_acknowledged": True, "modes": ["listen", "whisper"]},
    )
    assert settings["modes"] == ["listen", "whisper"]

    started = await spy()
    assert started["status"] == "ringing" and started["target_name"] == "Koffi Yao"
    request = fake.originated[-1]
    assert request["source"] == {"user": "u-2"}
    assert request["destination"] == {
        "context": "nimbora-supervision",
        "extension": "spy",
        "priority": 1,
    }
    # The line of the call in progress, with a trailing dash (one line only).
    assert request["variables"]["NIMBORA_SPY_TARGET"] == "PJSIP/koffi1001-"
    assert request["variables"]["NIMBORA_SPY_OPTIONS"] == "qE"

    await spy(mode="whisper")
    assert fake.originated[-1]["variables"]["NIMBORA_SPY_OPTIONS"] == "qwE"
    with pytest.raises(pbx.PbxRouteError) as barge:
        await spy(mode="barge")
    assert barge.value.status == 403

    for supervisor, target, status in (
        ("u-1", "u-1", 409),  # own extension
        ("u-1", "u-2", 409),  # Aya is not on a call
        ("u-2", "u-404", 404),
    ):
        with pytest.raises(pbx.PbxRouteError) as refused:
            await spy(supervisor, target)
        assert refused.value.status == status

    # Restricted to listed supervisors; protected extensions are never heard.
    await supervision.save_settings(org.id, {"supervisors": ["u-1"]})
    with pytest.raises(pbx.PbxRouteError) as not_listed:
        await spy()
    assert not_listed.value.status == 403
    await supervision.save_settings(org.id, {"supervisors": [], "protected": ["u-1"]})
    with pytest.raises(pbx.PbxRouteError) as protected:
        await spy()
    assert protected.value.status == 403
    live = await supervision.live(org.id, use_cache=False)
    assert live["calls"][0]["spyable"] is False

    # The supervisor's own phone already in a call: refused.
    await supervision.save_settings(org.id, {"protected": []})
    fake.calls.append({"call_id": "x", "user_uuid": "u-2", "status": "Up"})
    with pytest.raises(pbx.PbxRouteError) as busy:
        await spy()
    assert busy.value.status == 409

    sessions = await supervision.list_sessions(org.id)
    assert [s["mode"] for s in sessions] == ["whisper", "listen"]
    assert sessions[0]["target_name"] == "Koffi Yao"
    assert sessions[0]["supervisor_name"] == "Aya Diallo"


async def test_unexpected_line_names_are_refused(db_session, monkeypatch):
    fake = FakePbx()
    fake.user_endpoints["sip-u1"]["name"] = "koffi,qB"  # would inject options
    _, org = await _setup(db_session, monkeypatch, fake)
    await supervision.save_settings(
        org.id, {"enabled": True, "notice_acknowledged": True}
    )
    with pytest.raises(pbx.PbxRouteError):
        await supervision.start_spy(
            org.id,
            supervisor_user_uuid="u-2",
            target_user_uuid="u-1",
            mode="listen",
            requested_by_user_id=None,
        )
    assert not fake.originated


def test_periods_follow_the_company_timezone():
    now = datetime(2026, 11, 21, 23, 30, tzinfo=UTC)
    assert supervision.period_bounds("today", "Europe/Paris", now) == (
        "2026-11-22T00:00:00",
        "2026-11-23T00:00:00",
    )
    assert supervision.period_bounds("yesterday", "UTC", now) == (
        "2026-11-20T00:00:00",
        "2026-11-21T00:00:00",
    )
    assert supervision.period_bounds("7d", "UTC", now)[0] == "2026-11-15T00:00:00"
    with pytest.raises(pbx.PbxRouteError):
        supervision.period_bounds("forever", "UTC", now)


async def test_statistics(db_session, monkeypatch):
    fake = FakePbx()
    _, org = await _setup(db_session, monkeypatch, fake)
    await supervision.save_settings(org.id, {"sla_seconds": 30})
    stats = await supervision.statistics(org.id, "7d")
    queue = stats["queues"][0]
    assert queue["name"] == "Ventes" and queue["received"] == 40
    assert queue["answered_rate"] == 87.18 and queue["service_level"] == 76.47
    assert queue["unanswered"] == 1
    agent = stats["agents"][0]
    assert agent["name"] == "Koffi Yao" and agent["answered"] == 21
    assert agent["average_talk_seconds"] == 4380 // 21
    assert agent["occupancy"] == round(100 * 4380 / 25200, 1)
    assert stats["totals"]["answered_rate"] == round(100 * 34 / 39, 1)
    assert stats["totals"]["service_level"] == 76.5
    sent = fake.stat_requests[0]
    assert sent["qos_threshold"] == "30" and sent["timezone"]
    assert sent["from"] < sent["until"]


async def test_routes(db_session, monkeypatch, test_client_factory):
    fake = FakePbx()
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    fake.users[1]["email"] = email.upper()  # matched case-insensitively
    user, _ = await _setup(db_session, monkeypatch, fake, email=email)
    async with test_client_factory(user) as client:
        live = await client.get("/api/v1/pbx/supervision/live")
        assert live.status_code == 200 and live.json()["queues"][0]["waiting"] == 1

        settings = await client.get("/api/v1/pbx/supervision/settings")
        assert settings.json()["enabled"] is False
        assert settings.json()["my_extension"] == "u-2"
        extensions = settings.json()["extensions"]
        assert [e["extension"] for e in extensions] == ["1001", "1002"]
        assert all("email" not in e for e in extensions)  # not exposed

        spy = {"supervisor_user_uuid": "u-2", "target_user_uuid": "u-1"}
        refused = await client.post("/api/v1/pbx/supervision/spy", json=spy)
        assert refused.status_code == 409 and "activée" in refused.json()["detail"]

        bad = await client.put(
            "/api/v1/pbx/supervision/settings", json={"enabled": True}
        )
        assert bad.status_code == 422
        saved = await client.put(
            "/api/v1/pbx/supervision/settings",
            json={"enabled": True, "notice_acknowledged": True, "sla_seconds": 25},
        )
        assert saved.status_code == 200 and saved.json()["sla_seconds"] == 25

        started = await client.post(
            "/api/v1/pbx/supervision/spy", json={**spy, "mode": "barge"}
        )
        assert started.status_code == 200 and started.json()["status"] == "ringing"
        sessions = (await client.get("/api/v1/pbx/supervision/sessions")).json()
        assert sessions["sessions"][0]["mode"] == "barge"
        assert sessions["sessions"][0]["requested_by_user_id"] == user.id

        stats = await client.get("/api/v1/pbx/supervision/statistics?period=30d")
        assert stats.status_code == 200 and stats.json()["sla_seconds"] == 25
        assert (
            await client.get("/api/v1/pbx/supervision/statistics?period=ever")
        ).status_code == 422


def test_dialplan_validates_what_nimbora_sends():
    text = DIALPLAN.read_text()
    assert "[nimbora-supervision]" in text and "exten => spy,1" in text
    assert "ChanSpy(${NIMBORA_SPY_TARGET},${NIMBORA_SPY_OPTIONS})" in text
    # Every option string the service sends passes the dialplan's own check.
    import re

    pattern = re.search(r'REGEX\("\^q\[wB\]\?E\$"', text)
    assert pattern
    for options in supervision.SPY_OPTIONS.values():
        assert re.fullmatch(r"q[wB]?E", options)
    assert (
        supervision.DIALPLAN_CONTEXT == "nimbora-supervision"
        and supervision.DIALPLAN_EXTENSION == "spy"
    )


# ------------------------------------------------------------- real time


class FakeSocket:
    """Stands in for a Starlette WebSocket."""

    def __init__(self):
        import asyncio

        self.sent: list[dict] = []
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def send_json(self, data):
        self.sent.append(data)

    async def receive_text(self):
        message = await self.inbox.get()
        if message is None:
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect()
        return message

    def parts(self, kind):
        return [m["data"] for m in self.sent if m["type"] == kind]


async def _wait_for(predicate, timeout=5.0):
    import asyncio

    for _ in range(int(timeout / 0.05)):
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached")


async def test_stream_pushes_changes_on_pbx_events(db_session, monkeypatch):
    import asyncio

    from api.services.supervision import stream

    monkeypatch.setattr(stream, "PBX_REFRESH_SECONDS", 3600)
    monkeypatch.setattr(stream, "AI_REFRESH_SECONDS", 3600)
    monkeypatch.setattr(stream, "DEBOUNCE_SECONDS", 0.01)
    fake = FakePbx()
    user, org = await _setup(db_session, monkeypatch, fake)
    socket = FakeSocket()
    task = asyncio.create_task(stream.run(socket, org.id, user.id))
    try:
        await _wait_for(lambda: socket.parts("pbx") and socket.parts("ai"))
        assert socket.parts("pbx")[0]["queues"][0]["waiting"] == 1
        assert socket.parts("ai")[0]["ai_calls"] == []
        await asyncio.sleep(0.3)  # let the subscription settle

        # A caller leaves the queue; the webhook tells the consoles.
        fake.queue_entries["ventes"] = []
        connection = await db_session.get_pbx_connection(org.id)
        assert await pbx.handle_event(connection, "call_ended", {}) == "notified"
        await _wait_for(lambda: len(socket.parts("pbx")) == 2)
        assert socket.parts("pbx")[1]["queues"][0]["waiting"] == 0

        # Nothing changed: nothing is sent.
        await stream.notify(org.id, "pbx")
        await asyncio.sleep(0.4)
        assert len(socket.parts("pbx")) == 2

        # The console can ask for a refresh.
        fake.queue_entries["ventes"] = [{"Position": "1", "Wait": "3"}]
        await socket.inbox.put('{"type": "refresh"}')
        await _wait_for(lambda: len(socket.parts("pbx")) == 3)
        assert socket.parts("pbx")[2]["kpis"]["waiting"] == 1
    finally:
        await socket.inbox.put(None)
        await asyncio.wait_for(task, 5)


async def test_stream_without_pbx(db_session):
    import asyncio

    from api.services.supervision import stream

    user = await db_session.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db_session.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    socket = FakeSocket()
    task = asyncio.create_task(stream.run(socket, org.id, user.id))
    await _wait_for(
        lambda: socket.sent and any(m["type"] == "pbx" for m in socket.sent)
    )
    assert socket.parts("pbx") == [None]  # no PBX connected
    await socket.inbox.put(None)
    await asyncio.wait_for(task, 5)


def test_running_clocks_alone_are_not_a_change():
    from api.services.supervision import stream

    view = {
        "at": "t1",
        "queues": [{"waiting": 1, "longest_wait_seconds": 10}],
        "calls": [{"call_id": "c", "seconds": 5}],
    }
    later = {
        "at": "t2",
        "queues": [{"waiting": 1, "longest_wait_seconds": 13}],
        "calls": [{"call_id": "c", "seconds": 8}],
    }
    changed = {**later, "queues": [{"waiting": 2, "longest_wait_seconds": 13}]}
    assert stream._comparable(view) == stream._comparable(later)
    assert stream._comparable(view) != stream._comparable(changed)
    assert stream._comparable(None) == "null"

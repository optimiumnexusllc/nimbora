"""Live supervision: AI call feed & commands, Asterisk snapshot, spy, presence."""

import asyncio
import json
import random
import time
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.services.language.detection import DIRECTIVE_HEADER, language_directive
from api.services.supervision import asterisk_live, live_calls
from api.services.supervision.call_actions import (
    SECTION_HEADER,
    SupervisorActions,
    with_supervisor_section,
)


def _run_id() -> int:
    return random.randint(10**8, 10**9)


def test_feed_event_mapping():
    assert (
        live_calls.feed_event(
            {
                "type": "rtf-user-transcription",
                "payload": {"text": "Bonjour", "final": True},
            }
        )["kind"]
        == "caller"
    )
    assert (
        live_calls.feed_event(
            {
                "type": "rtf-user-transcription",
                "payload": {"text": "Bon", "final": False},
            }
        )
        is None
    )
    assert (
        live_calls.feed_event({"type": "rtf-bot-text", "payload": {"text": " "}})
        is None
    )
    tool = live_calls.feed_event(
        {"type": "rtf-function-call-start", "payload": {"function_name": "lookup"}}
    )
    assert tool["kind"] == "tool" and tool["name"] == "lookup"
    assert live_calls.feed_event({"type": "rtf-ttfb-metric", "payload": {}}) is None


async def test_publisher_feed_state_commands_and_cleanup():
    org, run = _run_id(), _run_id()
    publisher = live_calls.LiveCallPublisher(
        organization_id=org,
        run_id=run,
        meta={
            "agent_name": "Accueil",
            "caller": "+22790123456",
            "direction": "inbound",
        },
    )
    received = []

    async def instruct(command):
        received.append(command)
        return {"status": "ok"}

    publisher.on_command("instruct", instruct)
    await publisher.start()
    try:
        tee_calls = []

        async def browser(message):
            tee_calls.append(message["type"])

        tee = publisher.wrap_sender(browser)
        await tee(
            {
                "type": "rtf-user-transcription",
                "payload": {"text": "Je veux résilier", "final": True},
            }
        )
        await tee({"type": "rtf-bot-started-speaking", "payload": {}})
        await tee({"type": "rtf-bot-text", "payload": {"text": "Je comprends,"}})
        await tee({"type": "rtf-bot-text", "payload": {"text": "voyons cela."}})
        assert tee_calls[0] == "rtf-user-transcription"  # browser still served

        calls = await live_calls.list_live_calls(org)
        assert len(calls) == 1
        card = calls[0]
        assert card["agent_name"] == "Accueil" and card["turns"] == 1
        assert card["last_caller_text"] == "Je veux résilier"
        assert card["last_agent_text"] == "Je comprends, voyons cela."
        assert card["state"] == "agent_speaking"

        events = await live_calls.read_events(run)
        kinds = [e["kind"] for e in events]
        assert kinds == ["started", "caller", "agent", "agent"]
        last_seq = events[1]["seq"]
        assert [
            e["kind"] for e in await live_calls.read_events(run, after=last_seq)
        ] == [
            "agent",
            "agent",
        ]

        # A command through Redis pub/sub reaches the call's handler.
        for _ in range(50):
            if await live_calls.send_command(
                run,
                {
                    "action": "instruct",
                    "text": "Propose la remise de 10 %",
                    "by": "sup",
                },
            ):
                break
            await asyncio.sleep(0.05)
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.05)
        assert received[0]["text"] == "Propose la remise de 10 %"
        await asyncio.sleep(0.1)
        supervisor_events = [
            e for e in await live_calls.read_events(run) if e["kind"] == "supervisor"
        ]
        assert supervisor_events[-1]["status"] == "ok"
        unknown = await publisher.handle_command(json.dumps({"action": "dance"}))
        assert unknown["status"] == "error"
    finally:
        await publisher.stop()
    assert await live_calls.list_live_calls(org) == []
    assert (await live_calls.read_events(run))[-1]["kind"] == "ended"


async def test_stale_calls_are_pruned():
    org, run = _run_id(), _run_id()
    redis = await live_calls.get_redis()
    await redis.hset(
        live_calls.ORG_KEY.format(org=org),
        str(run),
        json.dumps({"run_id": run, "heartbeat_at": time.time() - 600, "started_at": 0}),
    )
    assert await live_calls.list_live_calls(org) == []
    assert not await live_calls.is_live(org, run)


def test_supervisor_section_stays_before_language_section():
    prompt = f"Tu es l'agent.\n\n{language_directive('en')}"
    once = with_supervisor_section(prompt, ["Sois bref"])
    twice = with_supervisor_section(once, ["Sois bref", "Propose un rappel"])
    assert twice.count(SECTION_HEADER) == 1 and twice.count(DIRECTIVE_HEADER) == 1
    assert twice.index(SECTION_HEADER) < twice.index(DIRECTIVE_HEADER)
    assert "- Propose un rappel" in twice
    assert with_supervisor_section(twice, []) == prompt


def test_composer_keeps_supervisor_instructions_across_nodes():
    from api.services.workflow.pipecat_engine_context_composer import (
        compose_system_prompt_for_node,
    )

    node = SimpleNamespace(id="n2", prompt="Étape paiement.", add_global_prompt=False)
    composed = compose_system_prompt_for_node(
        node=node,
        workflow=SimpleNamespace(global_node_id=None, nodes={"n2": node}),
        format_prompt=lambda text: text,
        has_recordings=False,
        supervisor_instructions=["Ne propose pas de remise"],
        language_directive=language_directive("es"),
    )
    assert "Ne propose pas de remise" in composed.text
    assert composed.text.index(SECTION_HEADER) < composed.text.index(DIRECTIVE_HEADER)


class FakeLLM:
    def __init__(self):
        self.instructions = []

    async def _update_settings(self, delta):
        self.instructions.append(delta.system_instruction)
        return {}


def _engine():
    spoken, ended = [], []

    class Speech:
        async def wait(self):
            return None

    async def queue_text_message(text, append_to_context=False):
        spoken.append(text)
        return True

    async def queue_speech(text):
        spoken.append(text)
        return Speech()

    async def end_call_with_reason(reason, abort_immediately=False):
        ended.append(reason)

    engine = SimpleNamespace(
        active_agent=SimpleNamespace(llm=FakeLLM(), system_prompt="Tu es l'agent."),
        _call_context_vars={},
        queue_text_message=queue_text_message,
        queue_speech=queue_speech,
        end_call_with_reason=end_call_with_reason,
        set_call_disposition=lambda d: ended.append(d),
        _custom_tool_manager=None,
        context=None,
    )
    return engine, spoken, ended


async def test_supervisor_actions_on_engine(monkeypatch):
    engine, spoken, ended = _engine()
    actions = SupervisorActions(engine)
    assert (await actions.instruct({"text": "Vouvoie le client"}))["status"] == "ok"
    await actions.instruct({"text": "Propose un rappel demain"})
    prompt = engine.active_agent.system_prompt
    assert prompt.count(SECTION_HEADER) == 1 and "- Vouvoie le client" in prompt
    assert engine.active_agent.llm.instructions[-1] == prompt
    assert engine._call_context_vars["supervisor_instructions"] == [
        "Vouvoie le client",
        "Propose un rappel demain",
    ]
    assert (await actions.instruct({"text": " "}))["status"] == "error"
    assert (await actions.say({"text": "Un instant, je vérifie."}))["status"] == "ok"
    assert spoken == ["Un instant, je vérifie."]
    assert (await actions.hangup({"text": "Au revoir."}))["status"] == "ok"
    assert ended == ["supervisor_hangup", "end_call"]

    # Take-over reuses the transfer tool with a queue destination.
    captured = {}

    class FakeManager:
        def __init__(self, engine, runtime=None):
            pass

        def _create_transfer_call_handler(self, tool, name):
            captured["destination"] = tool.definition["config"]["destination"]

            async def handler(params):
                await params.result_callback(
                    captured.get("result", {"status": "success"})
                )

            return handler

    import api.services.workflow.pipecat_engine_custom_tools as tools_module

    monkeypatch.setattr(tools_module, "CustomToolManager", FakeManager)
    assert (await actions.takeover({"queue_slug": "support"}))["status"] == "ok"
    assert captured["destination"] == "queue:support"
    captured["result"] = {"status": "failed", "reason": "no agent"}
    failed = await actions.takeover({"queue_slug": "support"})
    assert failed == {"status": "error", "error": "no agent"}
    assert (await actions.takeover({}))["status"] == "error"
    # Or to a queue of the enterprise PBX.
    captured.pop("result")
    assert (await actions.takeover({"queue_slug": "pbx-queue:1"}))["status"] == "ok"
    assert captured["destination"] == "pbx-queue:1"


def _seat(org, ext, **kw):
    return SimpleNamespace(
        id=int(ext),
        organization_id=org,
        display_name=f"Agent {ext}",
        extension=ext,
        sip_username=f"t{org}_{ext}",
        is_active=True,
        presence=kw.get("presence", "available"),
        presence_reason=kw.get("reason"),
        presence_changed_at=None,
        is_supervisor=kw.get("supervisor", False),
    )


def test_build_snapshot_from_ari():
    now = datetime(2026, 11, 21, 10, 0, tzinfo=UTC).timestamp()
    created = "2026-11-21T09:58:00.000+0000"
    seats = [
        _seat(3, "2001"),
        _seat(3, "2002"),
        _seat(3, "2003", presence="paused", reason="Pause déjeuner"),
        _seat(3, "2004"),
        _seat(4, "2001"),  # other tenant: never shown
    ]
    queue = SimpleNamespace(
        slug="support", name="Support", max_wait_seconds=120, agents=seats[:3]
    )
    channels = [
        {
            "id": "c1",
            "name": "PJSIP/t3_2001-00000001",
            "state": "Up",
            "creationtime": created,
            "connected": {"number": "+22790123456", "name": "Moussa"},
        },
        {
            "id": "q1",
            "name": "Local/t3-support@nimbora-queues-00000002;2",
            "state": "Up",
            "creationtime": "2026-11-21T09:59:00.000+0000",
            "caller": {"number": "+33612345678"},
            "dialplan": {"app_name": "Queue"},
        },
        {
            "id": "q2",
            "name": "Local/t3-support@nimbora-queues-00000003;2",
            "state": "Up",
            "creationtime": created,
            "dialplan": {"app_name": "AppQueue"},
        },
        {
            "id": "x",
            "name": "Local/t4-support@nimbora-queues-00000004;2",
            "state": "Up",
            "creationtime": created,
            "dialplan": {"app_name": "Queue"},
        },
    ]
    endpoints = [
        {
            "technology": "PJSIP",
            "resource": "t3_2001",
            "state": "online",
            "channel_ids": ["c1"],
        },
        {
            "technology": "PJSIP",
            "resource": "t3_2002",
            "state": "online",
            "channel_ids": [],
        },
        {
            "technology": "PJSIP",
            "resource": "t3_2003",
            "state": "online",
            "channel_ids": [],
        },
        {
            "technology": "PJSIP",
            "resource": "t3_2004",
            "state": "offline",
            "channel_ids": [],
        },
    ]
    snap = asterisk_live.build_snapshot(3, channels, endpoints, seats, [queue], now=now)
    status = {a["extension"]: a["status"] for a in snap["agents"]}
    assert status == {
        "2001": "on_call",
        "2002": "available",
        "2003": "paused",
        "2004": "offline",
    }
    on_call = snap["agents"][0]
    assert on_call["call"] == {
        "with_number": "+22790123456",
        "with_name": "Moussa",
        "seconds": 120,
    }
    support = snap["queues"][0]
    assert support["waiting"] == 1 and support["longest_wait_seconds"] == 60
    assert support["in_conversation"] == 1 and support["available_agents"] == 1
    assert snap["waiting_callers"] == [
        {"queue_slug": "support", "number": "+33612345678", "name": "", "seconds": 60}
    ]
    assert snap["busy_agents"] == 1


async def test_spy_validation_and_originate(monkeypatch):
    supervisor = _seat(3, "2009", supervisor=True)
    target = _seat(3, "2001")
    with pytest.raises(asterisk_live.SupervisionError):
        await asterisk_live.start_spy(
            supervisor_seat=supervisor, target_agent=target, mode="tap"
        )
    with pytest.raises(asterisk_live.SupervisionError):
        await asterisk_live.start_spy(
            supervisor_seat=supervisor, target_agent=_seat(4, "2001"), mode="listen"
        )
    with pytest.raises(asterisk_live.SupervisionError):
        await asterisk_live.start_spy(
            supervisor_seat=supervisor, target_agent=supervisor, mode="listen"
        )


def test_generated_config_pauses_agents_and_has_supervision_context():
    from api.services.contact_center.asterisk_config import (
        render_extensions,
        render_queues,
    )

    seats = [_seat(3, "2001"), _seat(3, "2002", presence="paused")]
    queue = SimpleNamespace(
        organization_id=3,
        slug="support",
        strategy="rrmemory",
        ring_timeout_seconds=20,
        wrapup_seconds=10,
        announce_position=True,
        agents=seats,
    )
    text = render_queues([queue])
    assert "PJSIP/t3_2001" in text and "PJSIP/t3_2002" not in text
    extensions = render_extensions([], [])
    assert "[nimbora-supervise]" in extensions
    assert "ChanSpy(${NIMBORA_SPY_TARGET},${NIMBORA_SPY_OPTIONS})" in extensions


# ---------------------------------------------------------------- routes


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


async def test_supervision_routes(
    db_session, test_client_factory, monkeypatch, tmp_path
):
    from api.routes import contact_center as cc_routes
    from api.routes import supervision as sup_routes
    from api.services.contact_center import asterisk_config
    from api.services.supervision import overview

    monkeypatch.setattr(sup_routes, "CONTACT_CENTER_ENABLED", True)
    monkeypatch.setattr(overview, "CONTACT_CENTER_ENABLED", True)
    monkeypatch.setattr(cc_routes, "CONTACT_CENTER_ENABLED", True)
    monkeypatch.setattr(asterisk_config, "ASTERISK_GENERATED_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(asterisk_config, "ASTERISK_ARI_PASSWORD", None)
    monkeypatch.setattr(asterisk_live, "ASTERISK_ARI_PASSWORD", None)

    user, org = await _new_org(db_session)
    other, _ = await _new_org(db_session)
    workflow = await db_session.create_workflow(
        "Accueil", {"nodes": [], "edges": []}, user.id, org.id
    )
    run = await db_session.create_workflow_run(
        name="WR-live",
        workflow_id=workflow.id,
        mode="twilio",
        user_id=user.id,
        organization_id=org.id,
    )
    await db_session.create_contact_center_queue(org.id, "support", {"name": "Support"})
    seat = await db_session.create_contact_center_agent(
        org.id,
        display_name="Awa",
        extension="2001",
        sip_username=f"t{org.id}_2001",
        sip_md5_cred="0" * 32,
        user_id=user.id,
    )
    colleague = await db_session.create_contact_center_agent(
        org.id,
        display_name="Ali",
        extension="2002",
        sip_username=f"t{org.id}_2002",
        sip_md5_cred="0" * 32,
    )

    publisher = live_calls.LiveCallPublisher(
        organization_id=org.id, run_id=run.id, meta={"agent_name": "Accueil"}
    )
    said = []

    async def say(command):
        said.append(command["text"])
        return {"status": "ok"}

    publisher.on_command("say", say)

    async with test_client_factory(user) as client:
        # Not live yet: actions refused.
        refused = await client.post(
            f"/api/v1/supervision/calls/{run.id}/actions",
            json={"action": "say", "text": "Allô"},
        )
        assert refused.status_code == 409
        await publisher.start()
        try:
            snap = (await client.get("/api/v1/supervision")).json()
            assert [c["run_id"] for c in snap["ai_calls"]] == [run.id]
            assert snap["telephony"] == "not_configured"
            assert snap["kpis"]["ai_calls"] == 1
            assert {a["extension"] for a in snap["agents"]} == {"2001", "2002"}
            assert snap["my_seat"]["is_supervisor"] is False

            assert (
                await client.post(
                    f"/api/v1/supervision/calls/{run.id}/actions",
                    json={"action": "takeover", "queue_slug": "nope"},
                )
            ).status_code == 404
            for _ in range(40):
                sent = await client.post(
                    f"/api/v1/supervision/calls/{run.id}/actions",
                    json={"action": "say", "text": "Je vous passe un conseiller."},
                )
                if sent.status_code == 200:
                    break
                await asyncio.sleep(0.05)
            assert sent.status_code == 200
            for _ in range(40):
                if said:
                    break
                await asyncio.sleep(0.05)
            assert said == ["Je vous passe un conseiller."]
            feed = (
                await client.get(f"/api/v1/supervision/calls/{run.id}/events")
            ).json()
            assert feed["live"] is True and feed["events"][0]["kind"] == "started"
        finally:
            await publisher.stop()

        # Spying needs supervisor rights on the seat.
        assert (
            await client.post(
                "/api/v1/supervision/spy", json={"agent_id": colleague.id}
            )
        ).status_code == 403
        await client.patch(
            f"/api/v1/contact-center/agents/{seat.id}", json={"is_supervisor": True}
        )
        spied = []

        async def fake_spy(*, supervisor_seat, target_agent, mode):
            spied.append((supervisor_seat.id, target_agent.id, mode))
            return "chan"

        monkeypatch.setattr(asterisk_live, "start_spy", fake_spy)
        ok = await client.post(
            "/api/v1/supervision/spy",
            json={"agent_id": colleague.id, "mode": "whisper"},
        )
        assert ok.status_code == 200 and spied == [(seat.id, colleague.id, "whisper")]

        # Presence: paused agents leave the queue.
        paused = await client.put(
            "/api/v1/contact-center/me/presence",
            json={"presence": "paused", "reason": "Pause déjeuner"},
        )
        assert paused.json()["presence"] == "paused"
        assert paused.json()["presence_reason"] == "Pause déjeuner"

    async with test_client_factory(other) as client:
        assert (
            await client.get(f"/api/v1/supervision/calls/{run.id}/events")
        ).status_code == 404
        assert (await client.get("/api/v1/supervision")).json()["ai_calls"] == []

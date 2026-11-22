"""Intelligent routing of AI hand-offs: VIP, usual advisor, skill, language."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from loguru import logger

from api.services.contact_center import smart_routing as routing
from api.services.contact_center.smart_routing import LiveState, NoAgentAvailable
from api.services.pbx import service as pbx
from api.tests.pbx_fake import TENANT, FakePbx, install

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
PHONE = "+2250102030405"

POLICY = {
    "default_destination": "pbx-queue:1",
    "vip_destination": "pbx-queue:9",
    "usual_advisor": True,
    "skills": [
        {"name": "Facturation", "destination": "pbx-queue:2"},
        {"name": "Support technique", "destination": "pbx-queue:3"},
    ],
    "languages": {"en": "pbx-queue:4"},
    "agents": {
        "1001": {"skills": ["Facturation"], "languages": ["fr"]},
        "1002": {"skills": ["Facturation"], "languages": ["en", "fr"]},
    },
    "when_unavailable": "queue",
}


def _state(free_queues=(), free_extensions=(), agents=("1001", "1002", "1003")):
    return LiveState(
        available_extensions=set(free_extensions),
        queue_available={q: 1 for q in free_queues},
        known=True,
        agent_extensions=set(agents),
    )


async def _org_with_customer(db, *, tags=(), advisor=None):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    profile = await db.get_or_create_customer_profile(org.id, PHONE, "102030405")
    attributes = {"usual_advisor": advisor} if advisor else {}
    await db.update_customer_profile(
        org.id, profile.id, {"tags": list(tags), "attributes": attributes}
    )
    return org, profile


async def _route(org, state, **kwargs):
    return await routing.route(
        org.id,
        caller_number=kwargs.pop("caller", PHONE),
        language=kwargs.pop("language", "fr"),
        skill=kwargs.pop("skill", None),
        policy=routing.clean_policy({**POLICY, **kwargs.pop("policy", {})}),
        state=state,
        now=NOW,
    )


# ------------------------------------------------------------------ policy


def test_policy_is_cleaned_and_validated():
    policy = routing.clean_policy(
        {
            "skills": [
                {"name": "Ventes", "destination": "pbx-queue:2"},
                {"name": "ventes ", "destination": "pbx-queue:5"},  # duplicate
                {"name": "", "destination": "pbx-queue:6"},
            ],
            "languages": {" EN ": "pbx-queue:4", "es": ""},
            "agents": {"1001": {"skills": ["Ventes", "Ventes"], "languages": ["FR"]}},
            "when_unavailable": "nonsense",
            "usual_advisor_days": 99999,
        }
    )
    assert policy["skills"] == [{"name": "Ventes", "destination": "pbx-queue:2"}]
    assert policy["languages"] == {"en": "pbx-queue:4"}
    assert policy["agents"] == {"1001": {"skills": ["Ventes"], "languages": ["fr"]}}
    assert policy["when_unavailable"] == "queue"
    assert policy["usual_advisor_days"] == 730
    with pytest.raises(ValueError):
        routing.clean_policy({"default_destination": "+33612345678"})
    with pytest.raises(ValueError):
        routing.clean_policy({"agents": {"abc": {}}})


def test_skill_names_match_without_accents_or_case():
    assert routing.normalize("  Réclamation-Client ") == "reclamation client"


# ------------------------------------------------------------------- order


async def test_vip_customer_goes_to_the_vip_destination(db_session):
    org, _ = await _org_with_customer(db_session, tags=["VIP"])
    decision = await _route(org, _state(free_queues={"9", "1"}), skill="facturation")
    assert (decision.destination, decision.reason) == ("pbx-queue:9", "vip")


async def test_usual_advisor_first_when_free(db_session):
    advisor = {
        "extension": "1007",
        "name": "Koffi Yao",
        "at": (NOW - timedelta(days=3)).isoformat(),
    }
    org, _ = await _org_with_customer(db_session, advisor=advisor)
    free = await _route(
        org, _state(free_queues={"2"}, free_extensions={"1007"}), skill="facturation"
    )
    assert (free.destination, free.reason) == ("pbx-extension:1007", "usual_advisor")
    assert "Koffi Yao" in free.explanation

    busy = await _route(
        org, _state(free_queues={"2"}, agents={"1007"}), skill="facturation"
    )
    assert (busy.destination, busy.reason) == ("pbx-queue:2", "skill")
    assert any("indisponible" in step for step in busy.steps)

    # Not a contact-center agent: busy only while on a call.
    on_call = LiveState(known=True, queue_available={"2": 1}, busy_extensions={"1007"})
    busy = await _route(org, on_call, skill="facturation")
    assert busy.reason == "skill"


async def test_old_advisor_is_forgotten(db_session):
    advisor = {"extension": "1007", "at": (NOW - timedelta(days=400)).isoformat()}
    org, _ = await _org_with_customer(db_session, advisor=advisor)
    decision = await _route(org, _state(free_queues={"1"}, free_extensions={"1007"}))
    assert decision.reason == "default"


async def test_skill_queue_then_skilled_agent_speaking_the_language(db_session):
    org, _ = await _org_with_customer(db_session)
    queue = await _route(org, _state(free_queues={"2"}), skill="Facturation")
    assert (queue.destination, queue.reason) == ("pbx-queue:2", "skill")

    # Queue full: a free agent with the skill, and the caller's language.
    agent = await _route(
        org,
        _state(free_extensions={"1001", "1002"}),
        skill="la facturation",
        language="en",
    )
    assert (agent.destination, agent.reason) == ("pbx-extension:1002", "skill_agent")


async def test_language_then_default(db_session):
    org, _ = await _org_with_customer(db_session)
    english = await _route(
        org, _state(free_queues={"4", "1"}), language="en", skill="inconnu"
    )
    assert (english.destination, english.reason) == ("pbx-queue:4", "language")
    assert any("inconnue" in step for step in english.steps)
    french = await _route(org, _state(free_queues={"1"}), language="fr")
    assert (french.destination, french.reason) == ("pbx-queue:1", "default")


async def test_nobody_free_queue_mode_waits_in_the_best_queue(db_session):
    org, _ = await _org_with_customer(db_session)
    decision = await _route(org, _state(), skill="support technique")
    assert (decision.destination, decision.reason) == ("pbx-queue:3", "fallback")


async def test_nobody_free_ai_mode_keeps_the_customer(db_session):
    org, _ = await _org_with_customer(db_session)
    with pytest.raises(NoAgentAvailable):
        await _route(org, _state(), policy={"when_unavailable": "ai"})


async def test_without_live_pbx_state_destinations_are_trusted(db_session):
    org, _ = await _org_with_customer(db_session)
    decision = await _route(org, LiveState(), skill="support")
    assert (decision.destination, decision.reason) == ("pbx-queue:3", "skill")


# ---------------------------------------------------------- transfer tool


async def test_callback_mode_schedules_a_human_callback(db_session, monkeypatch):
    org, _ = await _org_with_customer(db_session)
    await routing.save_policy(
        org.id, {**POLICY, "when_unavailable": "callback", "callback_delay_minutes": 30}
    )

    async def nobody(organization_id):
        return _state()

    monkeypatch.setattr(routing, "live_state", nobody)
    records = []
    sink = logger.add(lambda message: records.append(message.record["message"]))
    with pytest.raises(NoAgentAvailable) as error:
        await routing.resolve_for_transfer(
            org.id,
            call_context_vars={"caller_number": PHONE},
            gathered_context_vars={"call_language": "fr", "customer_name": "Awa"},
            arguments={"skill": "facturation"},
        )
    logger.remove(sink)
    assert error.value.callback_scheduled
    # One line per hand-off decision, with the skipped rules, without the number.
    line = next(r for r in records if r.startswith(f"[Routing org={org.id} handoff]"))
    assert "unavailable/callback → —" in line and "Facturation" in line
    assert PHONE not in line
    callbacks = await db_session.list_callback_requests(org.id)
    assert len(callbacks) == 1
    assert "facturation" in callbacks[0].reason and callbacks[0].customer_name == "Awa"
    delay = callbacks[0].scheduled_at - datetime.now(UTC)
    assert timedelta(minutes=25) < delay <= timedelta(minutes=30)


async def test_transfer_tool_resolves_a_smart_destination(db_session, monkeypatch):
    from api.services.workflow.tools import transfer_resolver
    from api.services.workflow.tools.custom_tool import tool_to_function_schema

    org, _ = await _org_with_customer(db_session)
    await routing.save_policy(org.id, POLICY)

    async def queues_free(organization_id):
        return _state(free_queues={"2"})

    monkeypatch.setattr(routing, "live_state", queues_free)
    resolved = await transfer_resolver.resolve_transfer_config(
        tool=None,
        config={"destination_source": "smart", "timeout": 25},
        arguments={"skill": "Facturation"},
        call_context_vars={"caller_number": PHONE},
        gathered_context_vars={"call_language": "fr"},
        organization_id=org.id,
        workflow_run_id=None,
    )
    assert (resolved.destination, resolved.source) == ("pbx-queue:2", "smart")
    assert resolved.metadata["reason"] == "skill"
    assert resolved.timeout_seconds == 25

    class Tool:
        tool_uuid = "t-1"
        name = "transferer"
        description = "Transférer"
        definition = {  # noqa: RUF012
            "type": "transfer_call",
            "config": {"destination_source": "smart"},
        }

    schema = tool_to_function_schema(Tool())
    assert "skill" in str(schema)


# ------------------------------------------------------------- learning


async def test_answered_pbx_call_teaches_the_usual_advisor(db_session, monkeypatch):
    from api.services.supervision import live_calls

    fake = FakePbx()
    org, profile = await _org_with_customer(db_session)
    install(monkeypatch, fake)
    await db_session.upsert_configuration(org.id, "CUSTOMER_MEMORY", {"enabled": True})
    connection = await db_session.save_pbx_connection(
        org.id,
        {
            "base_url": "https://pbx.ivoire-immo.ci",
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    store: dict = {}

    class Redis:
        async def set(self, key, value, nx=False, ex=None):
            if nx and key in store:
                return None
            store[key] = value
            return True

        async def publish(self, *args):
            return 0

    async def redis():
        return Redis()

    monkeypatch.setattr(live_calls, "get_redis", redis)
    cdr = {
        "id": 77001,
        "start": NOW.isoformat(),
        "answered": True,
        "duration": 240.0,
        "call_direction": "inbound",
        "source_extension": PHONE,
        "source_name": "Awa",
        # As the real engine writes it: the public number dialled, and the
        # employee's own extension apart (seen on the lab PBX, 26.11).
        "destination_extension": "2250700000001",
        "destination_internal_extension": "1004",
        "destination_name": "Aya Bamba",
    }
    assert await pbx.handle_event(connection, "call_log_created", cdr) == "recorded"
    refreshed = await db_session.get_customer_profile(org.id, profile.id)
    advisor = refreshed.attributes["usual_advisor"]
    assert (advisor["extension"], advisor["name"]) == ("1004", "Aya Bamba")

    # Outbound: the employee is the source's internal extension.
    out = {
        **cdr,
        "id": 77002,
        "call_direction": "outbound",
        "source_extension": "2250700000001",
        "source_internal_extension": "1006",
        "source_name": "Yao K",
        "destination_extension": PHONE,
        "destination_name": "",
    }
    assert await pbx.handle_event(connection, "call_log_created", out) == "recorded"
    refreshed = await db_session.get_customer_profile(org.id, profile.id)
    assert refreshed.attributes["usual_advisor"]["extension"] == "1006"

    # A short call does not change the advisor.
    assert not await routing.remember_advisor(
        org.id, profile.id, extension="1009", name="X", seconds=10
    )


def test_an_employee_who_is_not_an_agent_is_free_unless_on_a_call():
    state = LiveState(
        known=True,
        agent_extensions={"1001"},
        available_extensions=set(),
        busy_extensions={"1003"},
    )
    assert not state.destination_free("pbx-extension:1001")  # agent, not available
    assert state.destination_free("pbx-extension:1002")  # branch advisor, idle
    assert not state.destination_free("pbx-extension:1003")  # on a call


async def test_nobody_free_explains_every_skipped_rule(db_session):
    org, _ = await _org_with_customer(db_session)
    with pytest.raises(NoAgentAvailable) as raised:
        await _route(
            org, _state(), skill="facturation", policy={"when_unavailable": "ai"}
        )
    assert any("Facturation" in step for step in raised.value.steps)
    assert "Destination par défaut occupée" in raised.value.steps

"""AI agent → enterprise PBX hand-off: pbx-queue:/pbx-extension: destinations,
the call entering the PBX's own dialplan, the customer's number on the
human's phone, and the handoff card found again when the call rings."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from api.services.contact_center.destinations import (
    ContactCenterDestinationError,
    resolve_transfer_dial_string,
)
from api.services.pbx import client as client_module
from api.services.pbx import handoff
from api.services.pbx import service as pbx
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"
ARI = "http://pbx:5039"


@pytest.fixture(autouse=True)
def _clear():
    client_module._TOKENS.clear()
    yield


async def _org(db, monkeypatch, fake, *, linked=True):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    ari = await db.create_telephony_configuration(
        organization_id=org.id,
        name="PBX (ARI)",
        provider="ari",
        credentials={"ari_endpoint": ARI + "/", "app_name": "n", "app_password": "x"},
    )
    install(monkeypatch, fake)
    await db.save_pbx_connection(
        org.id,
        {
            "base_url": BASE,
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "ari_configuration_id": ari.id if linked else None,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    return user, org


def test_destinations_are_parsed_strictly():
    assert handoff.parse_destination("pbx-queue:1") == ("queue", "1")
    assert handoff.parse_destination(" PBX-Extension:1001 ") == ("extension", "1001")
    assert handoff.parse_destination("queue:support") is None
    assert handoff.parse_destination("+2250700112233") is None
    for bad in (
        "pbx-queue:ventes",
        "pbx-queue:1;x",
        "pbx-extension:10@ctx",
        "pbx-extension:",
    ):
        with pytest.raises(ContactCenterDestinationError):
            handoff.parse_destination(bad)
    assert handoff.card_key("queue", "1") == "pbx:q1"
    assert handoff.card_key("extension", "1001") == "pbx:e1001"


def test_the_human_sees_the_customer_number():
    assert (
        handoff.caller_id("+225 07 00 11 22 33", "Awa Koné")
        == '"IA · Awa Koné" <+2250700112233>'
    )
    assert handoff.caller_id("0700112233", None) == '"IA · Client" <0700112233>'
    # Quotes and angle brackets cannot break out of the caller-ID string.
    assert handoff.caller_id("+225", 'x" <evil>') == '"IA · x evil" <+225>'
    assert handoff.caller_id("", "Awa") is None


async def test_queue_and_extension_enter_the_pbx_dialplan(db_session, monkeypatch):
    fake = FakePbx()
    _, org = await _org(db_session, monkeypatch, fake)
    queue = await handoff.resolve(org.id, "queue", "1", ari_endpoint=ARI)
    assert queue.dial_string == "Local/3001@default" and queue.label == "Ventes"
    assert queue.card_key == "pbx:q1"
    person = await handoff.resolve(org.id, "extension", "1002", ari_endpoint=ARI)
    assert person.dial_string == "Local/1002@default" and person.label == "Aya Diallo"

    # The same through the transfer resolution used by the ARI provider.
    assert (
        await resolve_transfer_dial_string(
            "pbx-queue:1",
            organization_id=org.id,
            dial_string_template="PJSIP/{number}@operateur",
            ari_endpoint=ARI,
        )
        == "Local/3001@default"
    )
    for kind, value in (("queue", "99"), ("extension", "4040")):
        with pytest.raises(ContactCenterDestinationError):
            await handoff.resolve(org.id, kind, value, ari_endpoint=ARI)


async def test_only_calls_running_on_the_pbx_may_enter_it(db_session, monkeypatch):
    fake = FakePbx()
    _, org = await _org(db_session, monkeypatch, fake)
    with pytest.raises(
        ContactCenterDestinationError, match="does not run on the company PBX"
    ):
        await handoff.resolve(
            org.id, "queue", "1", ari_endpoint="http://autre-asterisk:8088"
        )
    with pytest.raises(ContactCenterDestinationError):
        await resolve_transfer_dial_string(
            "pbx-queue:1",
            organization_id=None,
            dial_string_template="x",
            ari_endpoint=ARI,
        )

    _, unlinked = await _org(db_session, monkeypatch, fake, linked=False)
    with pytest.raises(ContactCenterDestinationError, match="No ARI configuration"):
        await handoff.resolve(unlinked.id, "queue", "1", ari_endpoint=ARI)

    lonely = await db_session.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    no_pbx, _ = await db_session.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=lonely.id
    )
    with pytest.raises(ContactCenterDestinationError, match="No PBX"):
        await handoff.resolve(no_pbx.id, "queue", "1", ari_endpoint=ARI)


async def test_unexpected_dialplan_values_are_refused(db_session, monkeypatch):
    fake = FakePbx()
    fake.queues[0]["extensions"] = [{"exten": "3001", "context": "default,s,1)"}]
    _, org = await _org(db_session, monkeypatch, fake)
    with pytest.raises(ContactCenterDestinationError, match="Unexpected"):
        await handoff.resolve(org.id, "queue", "1", ari_endpoint=ARI)


async def test_ari_transfer_dials_the_pbx_with_the_customer_number(
    db_session, monkeypatch
):
    from api.services.telephony.providers.ari import provider as ari_module

    fake = FakePbx()
    _, org = await _org(db_session, monkeypatch, fake)
    sent = {}

    class Response:
        status = 200

        async def text(self):
            return '{"id": "chan-1"}'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, url, params=None, json=None, auth=None):
            sent.update(url=url, params=params, json=json)
            return Response()

    monkeypatch.setattr(ari_module.aiohttp, "ClientSession", Session)
    provider = ari_module.ARIProvider(
        {
            "ari_endpoint": ARI,
            "app_name": "n",
            "app_password": "x",
            "stasis_app_name": "nimbora_x",
            "organization_id": org.id,
        }
    )
    result = await provider.transfer_call(
        destination="pbx-queue:1",
        transfer_id=f"t-{uuid.uuid4().hex}",
        conference_name="c",
        timeout=30,
        handoff_id="card-1",
        caller_id='"IA · Awa" <+2250700112233>',
    )
    assert result["call_sid"] == "chan-1"
    assert sent["params"]["endpoint"] == "Local/3001@default"
    assert sent["params"]["callerId"] == '"IA · Awa" <+2250700112233>'
    assert sent["json"] == {"variables": {"__NIMBORA_HANDOFF": "card-1"}}


async def test_cards_are_found_again_for_the_ringing_call(db_session, monkeypatch):
    fake = FakePbx()
    _, org = await _org(db_session, monkeypatch, fake)
    old = await db_session.create_call_handoff(
        organization_id=org.id,
        queue_slug="pbx:q1",
        caller_number="+2250700112233",
        status="pending",
        reason="ancienne",
    )
    await db_session.update_call_handoff(
        org.id, old.id, {"created_at": datetime.now(UTC) - timedelta(hours=1)}
    )
    card = await db_session.create_call_handoff(
        organization_id=org.id,
        queue_slug="pbx:q1",
        caller_number="+2250700112233",
        status="pending",
        reason="Résiliation du bail",
        collected_data={"logement": "Cocody"},
    )
    await db_session.create_call_handoff(  # built-in queue card: not a PBX card
        organization_id=org.id, queue_slug="support", caller_number="+2250700112233"
    )
    for presented in ("0700112233", "+225 07 00 11 22 33", "002250700112233"):
        found = await handoff.card_for_caller(org.id, presented)
        assert found is not None and found.id == card.id
    assert handoff.caller_key("1001") is None  # extensions never match
    view = handoff.serialize_card(found)
    assert view["reason"] == "Résiliation du bail" and view["target"] == "pbx:q1"
    assert view["collected_data"] == {"logement": "Cocody"}
    assert await handoff.card_for_caller(org.id, "+33600000000") is None

    # PBX cards are closed from the PBX's call logs, never turned into team
    # callbacks by the built-in queue timeout.
    stale = await db_session.list_stale_pending_handoffs(
        datetime.now(UTC) + timedelta(hours=2)
    )
    assert all(not (h.queue_slug or "").startswith("pbx:") for h, _ in stale)


async def test_transfer_targets(db_session, monkeypatch):
    fake = FakePbx()
    _, org = await _org(db_session, monkeypatch, fake)
    targets = await handoff.transfer_targets(org.id)
    assert {
        "destination": "pbx-queue:1",
        "kind": "pbx_queue",
        "label": "Ventes",
        "number": "3001",
    } in targets
    assert any(
        t["destination"] == "pbx-extension:1002" and t["label"] == "Aya Diallo"
        for t in targets
    )


async def test_transfer_tool_creates_the_card_and_shows_the_customer(monkeypatch):
    """The AI's transfer tool, end to end up to the provider call."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from api.services.contact_center import handoff as cards
    from api.services.telephony.transfer_event_protocol import (
        TransferEvent,
        TransferEventType,
    )
    from api.services.workflow import pipecat_engine_custom_tools as tools
    from api.services.workflow.tools.transfer_resolver import ResolvedTransferConfig
    from api.tests.test_transfer_message_playback import (
        RecordingEngine,
        TransferToolModel,
    )

    engine = RecordingEngine()
    engine._gathered_context["customer_name"] = "Awa Koné"
    tool = TransferToolModel()
    outcome = TransferEvent(
        type=TransferEventType.DESTINATION_ANSWERED,
        transfer_id="tx-1",
        original_call_sid="caller",
    )
    transfer_manager = SimpleNamespace(
        store_transfer_context=AsyncMock(),
        publish_transfer_event=AsyncMock(return_value=outcome),
        wait_for_transfer_completion=AsyncMock(return_value=outcome),
        remove_transfer_context=AsyncMock(),
    )
    run = SimpleNamespace(
        id=7,
        mode="ari",
        initial_context={"caller_number": "+2250700112233"},
        gathered_context={"call_id": "caller"},
    )
    dialled = {}

    async def dial(**kwargs):
        dialled.update(kwargs)
        return {"call_sid": "destination"}

    provider = SimpleNamespace(
        supports_transfers=lambda: True,
        validate_config=lambda: True,
        supports_transfer_introduction=lambda: False,
        transfer_call=dial,
        end_transfer_leg=AsyncMock(),
    )
    created = {}

    async def create_card(engine, *, organization_id, workflow_run, queue_slug):
        created.update(queue_slug=queue_slug, run=workflow_run.id)
        return "card-42"

    monkeypatch.setattr(cards, "create_handoff_for_transfer", create_card)
    monkeypatch.setattr(
        tools.db_client, "get_workflow_run_by_id", AsyncMock(return_value=run)
    )
    monkeypatch.setattr(
        tools, "get_telephony_provider_for_run", AsyncMock(return_value=provider)
    )
    monkeypatch.setattr(
        tools, "get_call_transfer_manager", AsyncMock(return_value=transfer_manager)
    )
    monkeypatch.setattr(
        tools,
        "resolve_transfer_config",
        AsyncMock(
            return_value=ResolvedTransferConfig(
                destination="pbx-queue:1", timeout_seconds=30, source="static"
            )
        ),
    )
    await asyncio.wait_for(
        tools.CustomToolManager(engine)._create_transfer_call_handler(
            tool, "transfer_call"
        )(SimpleNamespace(arguments={}, result_callback=AsyncMock())),
        timeout=2,
    )
    assert created == {"queue_slug": "pbx:q1", "run": 7}
    assert dialled["destination"] == "pbx-queue:1"
    assert dialled["handoff_id"] == "card-42"
    assert dialled["caller_id"] == '"IA · Awa Koné" <+2250700112233>'

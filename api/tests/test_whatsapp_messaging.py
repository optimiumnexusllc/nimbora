"""WhatsApp conversations: webhook, agent turns, voice notes, memory, idle close."""

import hashlib
import hmac
import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from api.services.customer_memory import identity
from api.services.customer_memory.service import (
    customer_phone_from_context,
    interaction_channel,
    render_memory_prompt,
)
from api.services.whatsapp_messaging import service as wa
from api.services.whatsapp_messaging import transcribe
from api.services.whatsapp_messaging.graph import message_text, split_text


def test_message_types_and_splitting():
    assert message_text({"type": "text", "text": {"body": "Bonjour"}}) == (
        "Bonjour",
        None,
    )
    assert message_text({"type": "audio", "audio": {"id": "m1"}}) == (None, "m1")
    assert message_text(
        {"type": "interactive", "interactive": {"button_reply": {"title": "Oui"}}}
    ) == ("Oui", None)
    text, _ = message_text(
        {
            "type": "location",
            "location": {"latitude": 5.35, "longitude": -3.98, "name": "Cocody"},
        }
    )
    assert "Cocody" in text and "5.35" in text
    assert (
        "photo : facture"
        in message_text({"type": "image", "image": {"caption": "facture"}})[0]
    )
    assert message_text({"type": "reaction"}) == (None, None)
    long = "\n".join(["a" * 3000, "b" * 3000])
    assert [len(c) for c in split_text(long)] == [3000, 3000]
    assert split_text("") == []


async def test_voice_note_transcription_backends():
    def handler(request: httpx.Request):
        if request.url.host == "api.deepgram.com":
            assert request.headers["authorization"] == "Token dg"
            return httpx.Response(
                200,
                json={
                    "results": {
                        "channels": [{"alternatives": [{"transcript": "bonjour"}]}]
                    }
                },
            )
        assert request.url.path.endswith("/audio/transcriptions")
        assert b'name="language"' in request.content
        return httpx.Response(200, json={"text": " je cherche un appartement "})

    mock = httpx.MockTransport(handler)
    speaches = SimpleNamespace(
        provider="openai", base_url=None, api_key="k", model="whisper-1", language="fr"
    )
    assert (
        await transcribe.transcribe_voice_note(
            b"x", "audio/ogg", speaches, transport=mock
        )
        == "je cherche un appartement"
    )
    deepgram = SimpleNamespace(
        provider="deepgram", api_key="dg", model="nova-3", language="multi"
    )
    assert (
        await transcribe.transcribe_voice_note(
            b"x", "audio/ogg", deepgram, transport=mock
        )
        == "bonjour"
    )
    with pytest.raises(transcribe.TranscriptionUnavailable):
        await transcribe.transcribe_voice_note(
            b"x", "audio/ogg", SimpleNamespace(provider="azure")
        )


def test_channel_and_web_identity_rules():
    assert (
        interaction_channel(
            SimpleNamespace(initial_context={"channel": "whatsapp"}, mode="textchat")
        )
        == "whatsapp"
    )
    assert (
        interaction_channel(SimpleNamespace(initial_context={}, mode="textchat"))
        == "web"
    )
    assert (
        interaction_channel(
            SimpleNamespace(initial_context={"provider": "twilio"}, mode="twilio")
        )
        == "phone"
    )
    # An unverified web visitor's "phone" never links to a customer.
    assert (
        customer_phone_from_context({"channel": "web", "phone_number": "+33612345678"})
        is None
    )
    assert (
        customer_phone_from_context(
            {
                "channel": "web",
                "customer_verified": True,
                "caller_number": "+33612345678",
            }
        )
        == "+33612345678"
    )
    profile = SimpleNamespace(
        name="Awa", total_calls=3, last_seen_at=None, tags=[], notes=None, attributes={}
    )
    interactions = [
        SimpleNamespace(
            summary="Cherche un 3 pièces à Cocody",
            sentiment=None,
            transferred_to_queue=None,
            created_at=datetime(2026, 11, 20, tzinfo=UTC),
            channel="whatsapp",
        ),
    ]
    prompt = render_memory_prompt(profile, interactions)
    assert (
        "20/11/2026 sur WhatsApp : Cherche un 3 pièces à Cocody" in prompt
        or "sur WhatsApp : Cherche" in prompt
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


class FakeMessenger:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.read: list[str] = []
        self.media: tuple[bytes, str] = (b"ogg", "audio/ogg")

    async def send_text(self, to, body, *, reply_to=None):
        self.sent.append((to, body))
        return "wamid.out"

    async def mark_read(self, message_id, *, typing=True):
        self.read.append(message_id)

    async def download_media(self, media_id):
        return self.media


@pytest.fixture
def echo_agent(monkeypatch, db_session):
    """Replace the LLM turn by an echo written into the real text session."""
    from api.services import quota_service
    from api.services.workflow import text_chat_session_service as tcs

    async def fake_execute(*, workflow_id, run_id, text_session):
        data = tcs.normalize_text_chat_session_data(text_session.session_data)
        turn = data["turns"][-1]
        said = (turn.get("user_message") or {}).get("text")
        turn["status"] = "completed"
        turn["message_events_version"] = 1
        turn["events"] = [
            {
                "type": "bot_speech",
                "payload": {
                    "text": f"Écho : {said}" if said else "Bonjour, ici Ivoire Immo !"
                },
            }
        ]
        data["status"] = "idle"
        return await db_session.update_workflow_run_text_session(
            run_id,
            session_data=data,
            checkpoint=text_session.checkpoint,
            expected_revision=text_session.revision,
        )

    async def has_quota(**kwargs):
        return SimpleNamespace(has_quota=True, error_message=None)

    monkeypatch.setattr(tcs, "execute_pending_text_chat_turn", fake_execute)
    monkeypatch.setattr(quota_service, "authorize_workflow_run_start", has_quota)
    return fake_execute


async def _whatsapp_setup(db, *, assign_agent=True):
    user, org = await _new_org(db)
    workflow = await db.create_workflow(
        "Ivoire Immo", {"nodes": [], "edges": []}, user.id, org.id
    )
    waba = f"waba-{random.randint(10**6, 10**7)}"
    config = await db.create_telephony_configuration(
        organization_id=org.id,
        name="WhatsApp",
        provider="whatsapp",
        credentials={"access_token": "tok", "waba_id": waba, "app_secret": "s3cret"},
    )
    await db.create_phone_number(
        organization_id=org.id,
        telephony_configuration_id=config.id,
        address="+2250700000001",
        inbound_workflow_id=workflow.id if assign_agent else None,
    )
    return user, org, workflow, config


def _msg(text=None, *, audio=None, mid=None):
    message = {
        "id": mid or f"wamid.{uuid.uuid4().hex}",
        "from": "2250700112233",
        "timestamp": "1",
    }
    if audio:
        message.update({"type": "audio", "audio": {"id": audio}})
    else:
        message.update({"type": "text", "text": {"body": text}})
    return message


async def _send(config, message, messenger):
    return await wa.process_inbound_message(
        config=config,
        phone_number_id="pnid-1",
        business_number="+2250700000001",
        wa_id="2250700112233",
        profile_name="Awa",
        message=message,
        messenger=messenger,
    )


async def test_conversation_flow_with_memory(db_session, echo_agent):
    _, org, workflow, config = await _whatsapp_setup(db_session)
    # Awa called last week: WhatsApp must know her.
    profile = await db_session.get_or_create_customer_profile(
        org.id, "+2250700112233", "700112233"
    )
    await db_session.update_customer_profile(org.id, profile.id, {"name": "Awa Koné"})
    messenger = FakeMessenger()

    sent = await _send(
        config, _msg("Je cherche un appartement à Cocody pour 250 000 FCFA"), messenger
    )
    assert sent == [
        "Bonjour, ici Ivoire Immo !",
        "Écho : Je cherche un appartement à Cocody pour 250 000 FCFA",
    ]
    assert messenger.read and messenger.sent[0][0] == "2250700112233"
    conversation = await db_session.get_open_whatsapp_conversation(
        org.id, "pnid-1", "2250700112233"
    )
    assert conversation.message_count == 1 and conversation.workflow_id == workflow.id
    run = await db_session.get_workflow_run(
        conversation.workflow_run_id, organization_id=org.id
    )
    assert run.mode == "textchat"
    assert run.initial_context["channel"] == "whatsapp"
    assert run.initial_context["caller_number"] == "+2250700112233"
    assert (
        run.initial_context["customer_name"] == "Awa Koné"
    )  # memory from the phone call
    assert run.annotations["whatsapp"]["conversation_id"] == conversation.id

    # Second message: same run, no new greeting.
    sent = await _send(config, _msg("3 chambres"), messenger)
    assert sent == ["Écho : 3 chambres"]
    again = await db_session.get_open_whatsapp_conversation(
        org.id, "pnid-1", "2250700112233"
    )
    assert again.workflow_run_id == run.id and again.message_count == 2


async def test_voice_notes(db_session, echo_agent, monkeypatch):
    _, _, _, config = await _whatsapp_setup(db_session)
    messenger = FakeMessenger()

    async def fake_config(**kwargs):
        return SimpleNamespace(stt=SimpleNamespace(provider="speaches"))

    async def fake_transcribe(audio, mime, stt):
        assert audio == b"ogg"
        return "je veux visiter samedi"

    import api.services.configuration.run_model_configuration as rmc

    monkeypatch.setattr(
        rmc, "get_effective_ai_model_configuration_for_run", fake_config
    )
    monkeypatch.setattr(transcribe, "transcribe_voice_note", fake_transcribe)
    sent = await _send(config, _msg(audio="media-1"), messenger)
    assert sent[-1] == "Écho : [Message vocal] je veux visiter samedi"

    async def refuse(audio, mime, stt):
        raise transcribe.TranscriptionUnavailable("no")

    monkeypatch.setattr(transcribe, "transcribe_voice_note", refuse)
    sent = await _send(config, _msg(audio="media-2"), messenger)
    assert sent == [wa.VOICE_UNSUPPORTED_TEXT]


async def test_no_agent_or_no_quota(db_session, echo_agent, monkeypatch):
    _, _, _, config = await _whatsapp_setup(db_session, assign_agent=False)
    messenger = FakeMessenger()
    assert await _send(config, _msg("Bonjour"), messenger) == []

    _, _, _, config2 = await _whatsapp_setup(db_session)
    from api.services import quota_service

    async def no_quota(**kwargs):
        return SimpleNamespace(has_quota=False, error_message="Quota exceeded")

    monkeypatch.setattr(quota_service, "authorize_workflow_run_start", no_quota)
    assert await _send(config2, _msg("Bonjour"), messenger) == [wa.UNAVAILABLE_TEXT]


async def test_idle_conversation_closes_and_next_message_restarts(
    db_session, echo_agent, monkeypatch
):
    _, org, _, config = await _whatsapp_setup(db_session)
    messenger = FakeMessenger()
    await _send(config, _msg("Bonjour"), messenger)
    conversation = await db_session.get_open_whatsapp_conversation(
        org.id, "pnid-1", "2250700112233"
    )
    completed = []

    from api.services.workflow import text_chat_session_service as tcs

    async def fake_complete(*, run_id, text_session, expected_revision):
        completed.append(run_id)
        await db_session.update_workflow_run(run_id, is_completed=True)

    monkeypatch.setattr(tcs, "complete_text_chat_session", fake_complete)
    await db_session.update_whatsapp_conversation(
        org.id,
        conversation.id,
        {"last_inbound_at": datetime.now(UTC) - timedelta(hours=2)},
    )
    assert await wa.close_idle_conversations() >= 1
    assert completed == [conversation.workflow_run_id]
    closed = await db_session.get_whatsapp_conversation(org.id, conversation.id)
    assert closed.status == "closed"

    sent = await _send(config, _msg("Re-bonjour"), messenger)
    assert sent[0] == "Bonjour, ici Ivoire Immo !"
    fresh = await db_session.get_open_whatsapp_conversation(
        org.id, "pnid-1", "2250700112233"
    )
    assert (
        fresh.id != conversation.id
        and fresh.workflow_run_id != conversation.workflow_run_id
    )


async def test_webhook_signature_and_dedup(
    db_session, test_client_factory, monkeypatch
):
    user, org, _, config = await _whatsapp_setup(db_session)
    handled = []

    async def fake_handle(cfg, value):
        handled.append(value["messages"][0]["id"])
        return 1

    import api.services.whatsapp_messaging.service as service_module

    monkeypatch.setattr(service_module, "handle_messages_change", fake_handle)
    payload = {
        "entry": [
            {
                "id": config.credentials["waba_id"],
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {
                                "phone_number_id": "pnid-1",
                                "display_phone_number": "2250700000001",
                            },
                            "contacts": [
                                {"wa_id": "2250700112233", "profile": {"name": "Awa"}}
                            ],
                            "messages": [_msg("Bonjour", mid="wamid.same")],
                        },
                    }
                ],
            }
        ]
    }
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    async with test_client_factory(user) as client:
        path = next(
            r.path
            for r in client._transport.app.routes
            if getattr(r, "path", "").endswith("/whatsapp/webhook")
        )
        bad = await client.post(
            path,
            content=body,
            headers={
                "x-hub-signature-256": "sha256=00",
                "content-type": "application/json",
            },
        )
        assert bad.status_code in (401, 403)
        assert handled == []
        ok = await client.post(
            path,
            content=body,
            headers={
                "x-hub-signature-256": signature,
                "content-type": "application/json",
            },
        )
        assert ok.status_code == 200 and handled == ["wamid.same"]


async def test_duplicate_deliveries_are_answered_once(monkeypatch):
    scheduled = []

    async def fake_process(**kwargs):
        scheduled.append(kwargs["message"]["id"])

    monkeypatch.setattr(wa, "process_inbound_message", fake_process)
    mid = f"wamid.{uuid.uuid4().hex}"
    value = {
        "metadata": {
            "phone_number_id": "pnid-1",
            "display_phone_number": "2250700000001",
        },
        "messages": [_msg("a", mid=mid)],
    }
    config = SimpleNamespace(id=1, organization_id=1, credentials={})
    assert await wa.handle_messages_change(config, value) == 1
    assert await wa.handle_messages_change(config, value) == 0
    import asyncio

    await asyncio.sleep(0.05)
    assert scheduled == [mid]


async def test_web_identity_and_conversation_routes(
    db_session, test_client_factory, echo_agent
):
    user, org, _, config = await _whatsapp_setup(db_session)
    other, _ = await _new_org(db_session)
    await _send(config, _msg("Je cherche un studio"), FakeMessenger())
    async with test_client_factory(user) as client:
        secret = (await client.get("/api/v1/customers/identity")).json()["secret"]
        assert len(secret) == 64
        assert (await client.get("/api/v1/customers/identity")).json()[
            "secret"
        ] == secret
        conversations = (await client.get("/api/v1/whatsapp/conversations")).json()
        assert conversations[0]["customer_name"] == "Awa"
        detail = (
            await client.get(f"/api/v1/whatsapp/conversations/{conversations[0]['id']}")
        ).json()
        assert [m["role"] for m in detail["messages"]] == ["agent", "customer", "agent"]
        assert detail["messages"][1]["text"] == "Je cherche un studio"
        rotated = (await client.post("/api/v1/customers/identity/rotate")).json()[
            "secret"
        ]
        assert rotated != secret
    signature = identity.sign_phone(rotated, "+2250700112233")
    assert (
        await identity.verified_web_identity(
            org.id,
            {"customer_phone": "+225 07 00 11 22 33", "customer_signature": signature},
        )
        == "+2250700112233"
    )
    assert (
        await identity.verified_web_identity(
            org.id,
            {"customer_phone": "+2250700112234", "customer_signature": signature},
        )
        is None
    )
    assert (
        await identity.verified_web_identity(
            org.id, {"customer_phone": "+2250700112233"}
        )
        is None
    )
    async with test_client_factory(other) as client:
        assert (await client.get("/api/v1/whatsapp/conversations")).json() == []
        assert (
            await client.get(f"/api/v1/whatsapp/conversations/{conversations[0]['id']}")
        ).status_code == 404

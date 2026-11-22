"""WhatsApp conversations: the number's agent answers customers' messages.

Flow for each inbound message (webhook ``messages`` field, signature already
verified against the account's app secret):

1. de-duplicated (Meta retries), then handled in the background so the
   webhook answers at once;
2. serialized per conversation (Redis lock): two quick messages never run
   two agent turns at the same time;
3. read receipt + "typing…" indicator;
4. voice notes are transcribed with the agent's own speech recognizer;
5. the message goes to the conversation's text-chat run (created on the
   first message, with the customer's memory from every channel);
6. the agent's answer(s) are sent back.

A conversation closes after ``IDLE_MINUTES`` without a message (or when the
agent ends it): the run is completed — summary, customer memory, QA,
webhooks — and the next message starts a new run that remembers the past.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from api.services.whatsapp_messaging.graph import (
    WhatsAppMessenger,
    WhatsAppSendError,
    message_text,
)

IDLE_MINUTES = 30
DEDUP_TTL_SECONDS = 24 * 3600
LOCK_TIMEOUT_SECONDS = 180
UNAVAILABLE_TEXT = (
    "Notre assistant n'est pas disponible pour le moment. Merci de réessayer plus tard "
    "ou de nous appeler."
)
VOICE_UNSUPPORTED_TEXT = "Je n'ai pas pu écouter votre message vocal. Pouvez-vous me l'écrire, s'il vous plaît ?"

_background: set[asyncio.Task] = set()
_local_locks: dict[str, asyncio.Lock] = {}


def _canonical(number: str) -> str:
    from api.utils.telephony_address import normalize_telephony_address

    try:
        return normalize_telephony_address(number).canonical
    except Exception:
        digits = "".join(c for c in number if c.isdigit())
        return f"+{digits}" if digits else number


async def _redis():
    from api.services.supervision.live_calls import get_redis

    return await get_redis()


async def _first_delivery(message_id: str) -> bool:
    """Meta retries webhooks: handle each message id once."""
    if not message_id:
        return True
    try:
        redis = await _redis()
        return bool(
            await redis.set(
                f"nimbora:wa:msg:{message_id}", "1", nx=True, ex=DEDUP_TTL_SECONDS
            )
        )
    except Exception:
        return True


class _ConversationLock:
    """Redis lock across workers, in-process lock as fallback."""

    def __init__(self, key: str):
        self.key = key
        self._lock = None
        self._local = _local_locks.setdefault(key, asyncio.Lock())

    async def __aenter__(self):
        await self._local.acquire()
        try:
            redis = await _redis()
            self._lock = redis.lock(
                f"nimbora:wa:lock:{self.key}",
                timeout=LOCK_TIMEOUT_SECONDS,
                blocking_timeout=LOCK_TIMEOUT_SECONDS,
            )
            await self._lock.acquire()
        except Exception:
            self._lock = None
        return self

    async def __aexit__(self, *exc):
        try:
            if self._lock is not None:
                await self._lock.release()
        except Exception:
            pass
        self._local.release()


# ------------------------------------------------------------------ inbound


async def handle_messages_change(config, value: dict[str, Any]) -> int:
    """Schedule every new inbound message of one webhook change. Returns count."""
    metadata = value.get("metadata") or {}
    phone_number_id = str(metadata.get("phone_number_id") or "")
    business_number = _canonical(str(metadata.get("display_phone_number") or ""))
    names = {
        c.get("wa_id"): (c.get("profile") or {}).get("name")
        for c in value.get("contacts") or []
    }
    scheduled = 0
    for message in value.get("messages") or []:
        if not await _first_delivery(str(message.get("id") or "")):
            continue
        wa_id = str(message.get("from") or "")
        if not wa_id or not phone_number_id:
            continue
        task = asyncio.create_task(
            process_inbound_message(
                config=config,
                phone_number_id=phone_number_id,
                business_number=business_number,
                wa_id=wa_id,
                profile_name=names.get(wa_id),
                message=message,
            ),
            name=f"whatsapp-message-{message.get('id')}",
        )
        _background.add(task)
        task.add_done_callback(_background.discard)
        scheduled += 1
    for status in value.get("statuses") or []:
        if status.get("status") == "failed":
            errors = status.get("errors") or [{}]
            logger.warning(
                f"[WhatsApp] Message {status.get('id')} to {status.get('recipient_id')} "
                f"failed: {errors[0].get('title') or errors[0].get('message')}"
            )
    return scheduled


async def _agent_for_number(config, business_number: str):
    from api.db import db_client

    phones = await db_client.list_phone_numbers_for_config(config.id)
    phone = next(
        (p for p in phones if p.is_active and p.address_normalized == business_number),
        None,
    )
    if phone is None and len([p for p in phones if p.is_active]) == 1:
        phone = next(p for p in phones if p.is_active)
    if phone is None or not phone.inbound_workflow_id:
        return None
    return await db_client.get_workflow(
        phone.inbound_workflow_id, organization_id=config.organization_id
    )


async def process_inbound_message(
    *,
    config,
    phone_number_id: str,
    business_number: str,
    wa_id: str,
    profile_name: str | None,
    message: dict[str, Any],
    messenger: WhatsAppMessenger | None = None,
) -> list[str]:
    """Answer one inbound message. Returns the texts sent (for tests/logs)."""
    messenger = messenger or WhatsAppMessenger(
        phone_number_id, (config.credentials or {}).get("access_token") or ""
    )
    message_id = str(message.get("id") or "")
    async with _ConversationLock(f"{phone_number_id}:{wa_id}"):
        if message_id:
            await messenger.mark_read(message_id)
        try:
            return await _answer(
                config=config,
                phone_number_id=phone_number_id,
                business_number=business_number,
                wa_id=wa_id,
                profile_name=profile_name,
                message=message,
                messenger=messenger,
            )
        except Exception:
            logger.opt(exception=True).error(
                f"[WhatsApp] Could not answer message {message_id} from {wa_id}"
            )
            return []


async def _answer(
    *, config, phone_number_id, business_number, wa_id, profile_name, message, messenger
):
    from api.db import db_client

    workflow = await _agent_for_number(config, business_number)
    if workflow is None:
        logger.warning(
            f"[WhatsApp] No agent assigned to {business_number} (config {config.id}); message ignored"
        )
        return []
    conversation = await db_client.get_open_whatsapp_conversation(
        config.organization_id, phone_number_id, wa_id
    )
    if conversation is None:
        conversation = await db_client.open_whatsapp_conversation(
            organization_id=config.organization_id,
            telephony_configuration_id=config.id,
            phone_number_id=phone_number_id,
            business_number=business_number,
            customer_wa_id=wa_id,
            customer_name=profile_name,
            workflow_id=workflow.id,
            message_count=0,
        )
    now = datetime.now(UTC)
    conversation = await db_client.update_whatsapp_conversation(
        config.organization_id,
        conversation.id,
        {
            "last_inbound_at": now,
            "message_count": (conversation.message_count or 0) + 1,
            "customer_name": profile_name or conversation.customer_name,
        },
    )

    sent: list[str] = []
    run_id, greeting = await _ensure_run(conversation, workflow, profile_name)
    if run_id is None:
        await _send(messenger, wa_id, [UNAVAILABLE_TEXT], conversation, sent)
        return sent
    await _send(messenger, wa_id, greeting, conversation, sent)

    text, voice_media_id = message_text(message)
    if voice_media_id:
        text = await _transcribe(messenger, voice_media_id, conversation, run_id)
        if not text:
            await _send(messenger, wa_id, [VOICE_UNSUPPORTED_TEXT], conversation, sent)
            return sent
        text = f"[Message vocal] {text}"
    if not text:
        return sent

    replies, ended = await _run_turn(workflow.id, run_id, text)
    await _send(
        messenger,
        wa_id,
        replies,
        conversation,
        sent,
        reply_to=str(message.get("id") or "") or None,
    )
    if ended:
        await db_client.update_whatsapp_conversation(
            config.organization_id,
            conversation.id,
            {"status": "closed", "closed_at": datetime.now(UTC)},
        )
    return sent


async def _send(messenger, wa_id, texts, conversation, sent, reply_to=None) -> None:
    from api.db import db_client

    for text in texts:
        if not text or not text.strip():
            continue
        try:
            await messenger.send_text(
                wa_id, text, reply_to=reply_to if not sent else None
            )
            sent.append(text)
        except WhatsAppSendError as exc:
            logger.warning(f"[WhatsApp] Reply to {wa_id} failed: {exc}")
            return
    if sent:
        await db_client.update_whatsapp_conversation(
            conversation.organization_id,
            conversation.id,
            {"last_outbound_at": datetime.now(UTC)},
        )


# --------------------------------------------------------------- the agent


def _assistant_texts(turn: dict[str, Any]) -> list[str]:
    if turn.get("message_events_version") == 1:
        return [
            str(event.get("payload", {}).get("text"))
            for event in turn.get("events", [])
            if event.get("type") == "bot_speech"
            and event.get("payload", {}).get("text")
        ]
    message = turn.get("assistant_message") or {}
    return [message["text"]] if message.get("text") else []


async def _ensure_run(
    conversation, workflow, profile_name
) -> tuple[int | None, list[str]]:
    """The conversation's live run, or a new one (greeting returned)."""
    from api.db import db_client

    if conversation.workflow_run_id:
        run = await db_client.get_workflow_run(
            conversation.workflow_run_id, organization_id=conversation.organization_id
        )
        if run is not None and not run.is_completed:
            return run.id, []

    from api.enums import WorkflowRunMode
    from api.services.customer_memory.service import load_memory_context
    from api.services.quota_service import authorize_workflow_run_start
    from api.services.workflow.run_creation import prepare_workflow_run_inputs
    from api.services.workflow.text_chat_runner import default_text_chat_checkpoint
    from api.services.workflow.text_chat_session_service import (
        default_text_chat_session_data,
        execute_pending_text_chat_turn,
        initialize_text_chat_session,
        normalize_text_chat_session_data,
    )

    customer_number = _canonical(conversation.customer_wa_id)
    initial_context: dict[str, Any] = {
        "channel": "whatsapp",
        "direction": "inbound",
        "caller_number": customer_number,
        "called_number": conversation.business_number,
    }
    if profile_name:
        initial_context["whatsapp_profile_name"] = profile_name
    # The customer's history from every channel (phone calls, WhatsApp, web).
    try:
        async with asyncio.timeout(3):
            initial_context.update(
                await load_memory_context(conversation.organization_id, initial_context)
            )
    except Exception:
        logger.warning("[WhatsApp] Customer memory unavailable for this conversation")
    run_inputs = await prepare_workflow_run_inputs(
        db_client,
        workflow,
        initial_context=initial_context,
        include_template_context=True,
    )
    run = await db_client.create_workflow_run(
        name=f"WhatsApp {customer_number}",
        workflow_id=workflow.id,
        mode=WorkflowRunMode.TEXTCHAT.value,
        user_id=workflow.user_id,
        initial_context=run_inputs.initial_context,
        organization_id=conversation.organization_id,
        definition_id=run_inputs.definition_id,
    )
    quota = await authorize_workflow_run_start(
        workflow_id=workflow.id,
        organization_id=conversation.organization_id,
        workflow_run_id=run.id,
    )
    if not quota.has_quota:
        logger.warning(f"[WhatsApp] Org {conversation.organization_id} out of quota")
        return None, []
    await db_client.update_workflow_run(
        run.id,
        annotations={
            "whatsapp": {
                "conversation_id": conversation.id,
                "source": "whatsapp_messages",
                "modality": "text",
            }
        },
    )
    await db_client.update_whatsapp_conversation(
        conversation.organization_id, conversation.id, {"workflow_run_id": run.id}
    )
    text_session = await db_client.ensure_workflow_run_text_session(
        run.id,
        session_data=default_text_chat_session_data(),
        checkpoint=default_text_chat_checkpoint(),
    )
    text_session = await initialize_text_chat_session(
        run_id=run.id, text_session=text_session
    )
    text_session = await execute_pending_text_chat_turn(
        workflow_id=workflow.id, run_id=run.id, text_session=text_session
    )
    turns = normalize_text_chat_session_data(text_session.session_data)["turns"]
    return run.id, _assistant_texts(turns[-1]) if turns else []


async def _run_turn(workflow_id: int, run_id: int, text: str) -> tuple[list[str], bool]:
    from api.db import db_client
    from api.services.workflow.text_chat_session_service import (
        TextChatTurnInProgressError,
        append_text_chat_user_message,
        execute_pending_text_chat_turn,
        normalize_text_chat_session_data,
    )

    organization_id = await db_client.get_organization_id_by_workflow_run_id(run_id)
    text_session = await db_client.get_workflow_run_text_session(
        run_id, organization_id=organization_id
    )
    try:
        text_session = await append_text_chat_user_message(
            run_id=run_id,
            text_session=text_session,
            user_text=text,
            expected_revision=None,
        )
    except TextChatTurnInProgressError:
        # A previous turn was interrupted (worker restart): finish it first.
        text_session = await execute_pending_text_chat_turn(
            workflow_id=workflow_id, run_id=run_id, text_session=text_session
        )
        text_session = await append_text_chat_user_message(
            run_id=run_id,
            text_session=text_session,
            user_text=text,
            expected_revision=None,
        )
    text_session = await execute_pending_text_chat_turn(
        workflow_id=workflow_id, run_id=run_id, text_session=text_session
    )
    turns = normalize_text_chat_session_data(text_session.session_data)["turns"]
    run = await db_client.get_workflow_run(run_id, organization_id=organization_id)
    return (_assistant_texts(turns[-1]) if turns else []), bool(
        run and run.is_completed
    )


async def _transcribe(messenger, media_id, conversation, run_id) -> str | None:
    from api.db import db_client
    from api.services.configuration.run_model_configuration import (
        get_effective_ai_model_configuration_for_run,
    )
    from api.services.whatsapp_messaging.transcribe import (
        TranscriptionUnavailable,
        transcribe_voice_note,
    )

    try:
        audio, mime = await messenger.download_media(media_id)
        run = await db_client.get_workflow_run(
            run_id, organization_id=conversation.organization_id
        )
        config = await get_effective_ai_model_configuration_for_run(
            organization_id=conversation.organization_id, workflow_run=run
        )
        return await transcribe_voice_note(audio, mime, config.stt)
    except (TranscriptionUnavailable, WhatsAppSendError, ValueError) as exc:
        logger.warning(f"[WhatsApp] Voice note not transcribed: {exc}")
    except Exception:
        logger.opt(exception=True).warning("[WhatsApp] Voice note not transcribed")
    return None


# -------------------------------------------------------------- idle close


async def close_idle_conversations(_ctx=None, *, now: datetime | None = None) -> int:
    """arq cron: complete runs of conversations quiet for IDLE_MINUTES."""
    from api.db import db_client
    from api.services.workflow.text_chat_session_service import (
        complete_text_chat_session,
    )

    now = now or datetime.now(UTC)
    closed = 0
    for conversation in await db_client.list_idle_whatsapp_conversations(
        now - timedelta(minutes=IDLE_MINUTES)
    ):
        try:
            async with _ConversationLock(
                f"{conversation.phone_number_id}:{conversation.customer_wa_id}"
            ):
                if conversation.workflow_run_id:
                    run = await db_client.get_workflow_run(
                        conversation.workflow_run_id,
                        organization_id=conversation.organization_id,
                    )
                    if run is not None and not run.is_completed:
                        text_session = await db_client.get_workflow_run_text_session(
                            run.id, organization_id=conversation.organization_id
                        )
                        if text_session is not None:
                            await complete_text_chat_session(
                                run_id=run.id,
                                text_session=text_session,
                                expected_revision=None,
                            )
                await db_client.update_whatsapp_conversation(
                    conversation.organization_id,
                    conversation.id,
                    {"status": "closed", "closed_at": now},
                )
                closed += 1
        except Exception:
            logger.opt(exception=True).warning(
                f"[WhatsApp] Could not close conversation {conversation.id}"
            )
    return closed

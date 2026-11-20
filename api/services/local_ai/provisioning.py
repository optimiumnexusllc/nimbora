"""Provision a new organization on the platform's self-hosted AI stack.

With ``LOCAL_AI_ENABLED`` every tenant starts with two model connections —
the local LLM server (Ollama or vLLM, OpenAI-compatible) and the local speech
server (Speaches: faster-whisper STT, Kokoro/Piper TTS) — and a default
configuration that uses them, in the platform's default language. No API key,
no external account, no call leaves the platform.
"""

from __future__ import annotations

from loguru import logger

from api.constants import (
    LOCAL_DEFAULT_LANGUAGE,
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_MODEL,
    LOCAL_SPEECH_BASE_URL,
    LOCAL_STT_MODEL,
    LOCAL_TTS_MODEL,
    LOCAL_TTS_VOICE,
)
from api.services.local_ai.language_packs import KOKORO_MODEL, LANGUAGE_PACKS

LOCAL_LLM_CONNECTION_NAME = "LLM local (plateforme)"
LOCAL_SPEECH_CONNECTION_NAME = "Voix locale (plateforme)"
LOCAL_CONFIGURATION_NAME = "IA locale — par défaut"

SPEACHES_PROVIDER = "speaches"


def local_voice_for(language: str) -> tuple[str, str]:
    """(tts_model, tts_voice) for a language, honoring explicit overrides."""
    if LOCAL_TTS_MODEL and LOCAL_TTS_VOICE:
        return LOCAL_TTS_MODEL, LOCAL_TTS_VOICE
    pack = LANGUAGE_PACKS.get(language)
    voice = pack.default_voice if pack else None
    if voice is None:
        # No local voice for that language yet: answer in French by default.
        voice = LANGUAGE_PACKS["fr"].default_voice
    assert voice is not None
    return voice.model, voice.voice


def local_model_configuration_spec(
    llm_connection_uuid, speech_connection_uuid, language: str | None = None
) -> dict:
    language = (language or LOCAL_DEFAULT_LANGUAGE).lower()
    pack = LANGUAGE_PACKS.get(language)
    stt_language = pack.whisper_language if pack else language
    tts_model, tts_voice = local_voice_for(language)
    return {
        "version": 3,
        "mode": "pipeline",
        "llm": {
            "provider_connection_uuid": str(llm_connection_uuid),
            "settings": {"model": LOCAL_LLM_MODEL},
        },
        "stt": {
            "provider_connection_uuid": str(speech_connection_uuid),
            "settings": {"model": LOCAL_STT_MODEL, "language": stt_language},
        },
        "tts": {
            "provider_connection_uuid": str(speech_connection_uuid),
            "settings": {"model": tts_model, "voice": tts_voice},
        },
    }


def local_connections() -> list[dict]:
    return [
        {
            "name": LOCAL_LLM_CONNECTION_NAME,
            "provider": SPEACHES_PROVIDER,
            "credentials": {},
            "connection_settings": {"base_url": LOCAL_LLM_BASE_URL},
        },
        {
            "name": LOCAL_SPEECH_CONNECTION_NAME,
            "provider": SPEACHES_PROVIDER,
            "credentials": {},
            "connection_settings": {"base_url": LOCAL_SPEECH_BASE_URL},
        },
    ]


async def bootstrap_local_model_configuration(organization_id: int) -> str:
    from api.db import db_client

    configuration_uuid = (
        await db_client.bootstrap_default_model_configuration_from_connections(
            organization_id,
            connections=local_connections(),
            configuration_name=LOCAL_CONFIGURATION_NAME,
            configuration_for=lambda uuids: local_model_configuration_spec(*uuids),
        )
    )
    logger.info(
        "Provisioned local AI configuration {} for organization {}",
        configuration_uuid,
        organization_id,
    )
    return str(configuration_uuid)


__all__ = [
    "KOKORO_MODEL",
    "bootstrap_local_model_configuration",
    "local_model_configuration_spec",
    "local_voice_for",
]

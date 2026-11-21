"""Transcribe WhatsApp voice notes with the agent's own speech recognizer.

Supported: self-hosted Whisper (Speaches), OpenAI-compatible transcription
endpoints and Deepgram. Other recognizers are streaming-only here: the
agent then asks the customer to type.
"""

from __future__ import annotations

from typing import Any

import httpx

TIMEOUT = httpx.Timeout(60.0)


class TranscriptionUnavailable(RuntimeError):
    pass


def _provider(stt: Any) -> str:
    provider = getattr(stt, "provider", None)
    return str(getattr(provider, "value", provider) or "")


def _extension(mime: str) -> str:
    return {
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/amr": "amr",
        "audio/aac": "aac",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
    }.get(mime.split(";")[0].strip(), "ogg")


async def transcribe_voice_note(
    audio: bytes, mime: str, stt: Any, transport=None
) -> str:
    provider = _provider(stt)
    language = str(
        getattr(getattr(stt, "language", None), "value", getattr(stt, "language", None))
        or ""
    )
    if language.lower() in {"auto", "multi"}:
        language = ""
    if provider in {"speaches", "openai"}:
        base_url = (
            getattr(stt, "base_url", None) or "https://api.openai.com/v1"
        ).rstrip("/")
        if provider == "speaches":
            from api.utils.url_security import validate_user_configured_service_url

            validate_user_configured_service_url(
                base_url, field_name="base_url", allow_platform_services=True
            )
        model = getattr(stt, "model", None) or (
            "whisper-1" if provider == "openai" else "Systran/faster-whisper-large-v3"
        )
        if (
            provider == "openai"
            and model.startswith("gpt-4o")
            and "transcribe" not in model
        ):
            model = "whisper-1"
        data = {"model": model}
        if language:
            data["language"] = language.split("-")[0]
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
            response = await client.post(
                f"{base_url}/audio/transcriptions",
                headers={
                    "Authorization": f"Bearer {getattr(stt, 'api_key', None) or 'none'}"
                },
                data=data,
                files={"file": (f"voice.{_extension(mime)}", audio, mime)},
            )
        if response.status_code >= 300:
            raise TranscriptionUnavailable(
                f"Transcription failed ({response.status_code})"
            )
        return (response.json().get("text") or "").strip()
    if provider == "deepgram":
        params = {
            "model": getattr(stt, "model", None) or "nova-3",
            "smart_format": "true",
        }
        params.update(
            {"language": language} if language else {"detect_language": "true"}
        )
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
            response = await client.post(
                "https://api.deepgram.com/v1/listen",
                params=params,
                headers={
                    "Authorization": f"Token {getattr(stt, 'api_key', '')}",
                    "Content-Type": mime,
                },
                content=audio,
            )
        if response.status_code >= 300:
            raise TranscriptionUnavailable(
                f"Transcription failed ({response.status_code})"
            )
        channels = response.json().get("results", {}).get("channels") or [{}]
        alternatives = channels[0].get("alternatives") or [{}]
        return (alternatives[0].get("transcript") or "").strip()
    raise TranscriptionUnavailable(
        f"Voice notes are not supported with the {provider or 'configured'} recognizer"
    )

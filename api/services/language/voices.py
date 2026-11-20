"""The voice an agent speaks with in each language.

Resolution order for a language:

1. the agent's own choice (workflow setting ``language_detection.voices``);
2. for the self-hosted stack (Speaches), the language pack's default voice
   — Kokoro or Piper, model and voice together;
3. for multilingual cloud voices (ElevenLabs, Cartesia, Azure, Google…),
   the same voice with the service's ``language`` set, when the service
   exposes one;
4. otherwise the current voice: the LLM still answers in the new language.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class VoiceChoice:
    model: str | None = None
    voice: str | None = None
    language: str | None = None
    source: str = "unchanged"  # agent | language_pack | service_language | unchanged

    def is_change(self) -> bool:
        return any((self.model, self.voice, self.language))


def resolve_voice(
    language: str,
    *,
    provider: str | None,
    overrides: dict[str, dict[str, Any]] | None = None,
    service_has_language: bool = False,
) -> VoiceChoice:
    override = (overrides or {}).get(language) or {}
    if override.get("voice"):
        return VoiceChoice(
            model=override.get("model") or None,
            voice=override["voice"],
            language=language if service_has_language else None,
            source="agent",
        )
    if provider == "speaches":
        from api.services.local_ai.language_packs import LANGUAGE_PACKS

        pack = LANGUAGE_PACKS.get(language)
        if pack and pack.default_voice:
            return VoiceChoice(
                model=pack.default_voice.model,
                voice=pack.default_voice.voice,
                source="language_pack",
            )
        return VoiceChoice()
    if service_has_language:
        return VoiceChoice(language=language, source="service_language")
    return VoiceChoice()


def tts_provider(tts_config: Any) -> str | None:
    provider = getattr(tts_config, "provider", None)
    return str(getattr(provider, "value", provider)) if provider else None


async def apply_voice(tts: Any, choice: VoiceChoice) -> bool:
    """Apply a voice choice to a live TTS service. Never raises."""
    if tts is None or not choice.is_change():
        return False
    try:
        settings_type = type(tts._settings)
        fields: dict[str, Any] = {}
        if choice.model:
            fields["model"] = choice.model
        if choice.voice:
            fields["voice"] = choice.voice
        if choice.language and getattr(tts._settings, "language", None) is not None:
            fields["language"] = choice.language
        if not fields:
            return False
        changed = await tts._update_settings(settings_type(**fields))
        return bool(changed)
    except Exception:
        logger.opt(exception=True).warning("Could not switch the TTS voice")
        return False


def service_has_language(tts: Any) -> bool:
    """True when the live TTS service stores a language setting."""
    settings = getattr(tts, "_settings", None)
    return getattr(settings, "language", None) is not None

"""Per-call language controller: follow the caller's language.

When the policy decides the caller now speaks another language:

* the LLM gets a "Conversation language" section at the end of its system
  prompt (kept across node changes and agent transfers);
* the active agent's TTS switches to the voice of that language;
* ``call_language`` and ``languages_spoken`` are recorded in the call's
  gathered context (reports, webhooks, customer memory).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from api.services.language.detection import (
    LanguageSwitchPolicy,
    language_directive,
    normalize_language_code,
    with_language_directive,
)
from api.services.language.voices import (
    apply_voice,
    resolve_voice,
    service_has_language,
    tts_provider,
)
from loguru import logger

CONTEXT_LANGUAGE = "call_language"
CONTEXT_DIRECTIVE = "call_language_directive"


class CallLanguageController:
    def __init__(
        self,
        engine: Any,
        *,
        default_language: str,
        allowed: list[str] | None = None,
        voices: dict[str, dict[str, Any]] | None = None,
        tts_config: Any = None,
    ):
        self._engine = engine
        self.default_language = default_language
        self.allowed = set(allowed) | {default_language} if allowed else None
        self._voices = voices or {}
        self._provider = tts_provider(tts_config)
        self.policy = LanguageSwitchPolicy(
            current=default_language, allowed=self.allowed
        )
        self.history: list[dict[str, str]] = []
        self._voice_applied: dict[int, str] = {}

    @property
    def current(self) -> str:
        return self.policy.current

    # ------------------------------------------------------------- inputs
    async def on_transcript(self, text: str, reported_language: Any = None) -> bool:
        """Feed a final caller transcript. Returns True when the language changed."""
        try:
            new_language = self.policy.observe(text, reported_language)
        except Exception:
            logger.opt(exception=True).warning("Language detection failed")
            return False
        if new_language is None:
            return False
        await self.switch_to(new_language, reason="detected")
        return True

    async def start_in(self, language: str | None, reason: str) -> bool:
        """Start the call in a language (e.g. remembered from the last call)."""
        code = normalize_language_code(language)
        if not code or code == self.current:
            return False
        if self.allowed and code not in self.allowed:
            return False
        self.policy.current = code
        await self.switch_to(code, reason=reason)
        return True

    # ------------------------------------------------------------ effects
    async def switch_to(self, language: str, *, reason: str) -> None:
        self.policy.current = language
        engine = self._engine
        directive = (
            None
            if language == self.default_language and not self.history
            else language_directive(language)
        )
        context_vars = getattr(engine, "_call_context_vars", None)
        if isinstance(context_vars, dict):
            context_vars[CONTEXT_LANGUAGE] = language
            context_vars[CONTEXT_DIRECTIVE] = directive
        self.history.append(
            {
                "language": language,
                "reason": reason,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        gathered = getattr(engine, "_gathered_context", None)
        if isinstance(gathered, dict):
            gathered[CONTEXT_LANGUAGE] = language
            spoken = list(gathered.get("languages_spoken") or [self.default_language])
            if language not in spoken:
                spoken.append(language)
            gathered["languages_spoken"] = spoken
        logger.info(f"[language] Caller language is now '{language}' ({reason})")

        agent = getattr(engine, "active_agent", None)
        if agent is None:
            return
        await self._apply_prompt(agent, directive)
        await self.ensure_voice(agent)

    async def _apply_prompt(self, agent: Any, directive: str | None) -> None:
        llm = getattr(agent, "llm", None)
        current_prompt = getattr(agent, "system_prompt", None)
        if llm is None or current_prompt is None:
            return
        updated = with_language_directive(current_prompt, directive)
        if updated == current_prompt:
            return
        agent.system_prompt = updated
        try:
            from pipecat.services.settings import LLMSettings

            await llm._update_settings(LLMSettings(system_instruction=updated))
        except Exception:
            logger.opt(exception=True).warning("Could not update the reply language")

    async def ensure_voice(self, agent: Any) -> bool:
        """Give ``agent``'s TTS the current language's voice (once per language)."""
        tts = getattr(agent, "tts", None)
        if tts is None:
            return False
        key = id(tts)
        if self._voice_applied.get(key) == self.current:
            return False
        if key not in self._voice_applied and self.current == self.default_language:
            # Fresh agent in the starting language: keep its configured voice.
            self._voice_applied[key] = self.current
            return False
        provider = (
            tts_provider(getattr(agent, "user_config", None) and agent.user_config.tts)
            or self._provider
        )
        choice = resolve_voice(
            self.current,
            provider=provider,
            overrides=self._voices,
            service_has_language=service_has_language(tts),
        )
        if self.current == self.default_language and choice.source == "unchanged":
            # Back to the starting language with nothing better: restore the
            # agent's configured voice.
            choice = _configured_voice(agent)
        self._voice_applied[key] = self.current
        applied = await apply_voice(tts, choice)
        if applied:
            logger.info(
                f"[language] Voice for '{self.current}' applied ({choice.source})"
            )
        return applied


def _configured_voice(agent: Any):
    from api.services.language.voices import VoiceChoice

    config = getattr(getattr(agent, "user_config", None), "tts", None)
    if config is None:
        return VoiceChoice()
    return VoiceChoice(
        model=getattr(config, "model", None),
        voice=getattr(config, "voice", None) or getattr(config, "voice_id", None),
        language=getattr(config, "language", None),
        source="configured",
    )


def build_controller(
    engine: Any,
    workflow_configurations: dict | None,
    user_config: Any,
) -> CallLanguageController | None:
    """A controller when the agent enables language detection, else None."""
    raw = (workflow_configurations or {}).get("language_detection") or {}
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None
    stt = getattr(user_config, "stt", None)
    default = (
        normalize_language_code(raw.get("default_language"))
        or normalize_language_code(getattr(stt, "language", None))
        or normalize_language_code(
            getattr(getattr(user_config, "tts", None), "language", None)
        )
        or "fr"
    )
    voices = {
        str(code): value
        for code, value in (raw.get("voices") or {}).items()
        if isinstance(value, dict)
    }
    return CallLanguageController(
        engine,
        default_language=default,
        allowed=[c for c in raw.get("languages") or [] if isinstance(c, str)],
        voices=voices,
        tts_config=getattr(user_config, "tts", None),
    )

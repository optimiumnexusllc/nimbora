"""Self-hosted Whisper (Speaches) with automatic language detection.

With the STT language set to ``auto``, each segment is sent without a
language so Whisper detects it, and the detected language is put on the
``TranscriptionFrame``. The call's language controller reads it to switch
the agent's reply language and voice.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.services.speaches.stt import SpeachesSTTService
from pipecat.utils.types import assert_given

AUTO_LANGUAGE_VALUES = {"auto", "multi", ""}


def is_auto_language(language: Any) -> bool:
    return language is None or str(language).strip().lower() in AUTO_LANGUAGE_VALUES


class AutoLanguageSpeachesSTTService(SpeachesSTTService):
    """Speaches STT that lets Whisper detect the language of every segment."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.detected_language: str | None = None

    async def _transcribe(self, audio: bytes):
        from api.services.language.detection import normalize_language_code

        kwargs: dict[str, Any] = {
            "file": ("audio.wav", audio, "audio/wav"),
            "model": assert_given(self._settings.model),
            # verbose_json carries the detected language.
            "response_format": "verbose_json",
        }
        if self._settings.prompt is not None:
            kwargs["prompt"] = self._settings.prompt
        if self._settings.temperature is not None:
            kwargs["temperature"] = self._settings.temperature
        response = await self._client.audio.transcriptions.create(**kwargs)
        self.detected_language = normalize_language_code(
            getattr(response, "language", None)
        )
        return response

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        self.detected_language = None
        async for frame in super().run_stt(audio):
            if isinstance(frame, TranscriptionFrame) and self.detected_language:
                frame.language = self.detected_language
            yield frame

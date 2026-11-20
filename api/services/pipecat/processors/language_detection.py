"""Watch the caller's transcripts and tell the language controller.

Sits right after the STT. Frames are forwarded first, untouched; the
controller then decides (cheaply, synchronously in the common case) whether
the conversation changed language, before the user turn reaches the LLM.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class LanguageDetectionProcessor(FrameProcessor):
    def __init__(self, controller: Any, **kwargs):
        super().__init__(**kwargs)
        self._controller = controller

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)
        if (
            direction == FrameDirection.DOWNSTREAM
            and isinstance(frame, TranscriptionFrame)
            and frame.text
        ):
            try:
                await self._controller.on_transcript(
                    frame.text, getattr(frame, "language", None)
                )
            except Exception:
                logger.opt(exception=True).warning("Language controller failed")

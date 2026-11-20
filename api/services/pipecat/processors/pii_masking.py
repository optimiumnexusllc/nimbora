"""Mask payment and identity numbers before anyone sees them (PCI).

Card numbers, CVV, IBAN and social security numbers spoken by the caller are
masked *as the speech recognizer emits them*: the LLM, the live transcript
shown to supervisors, the stored transcript and the logs only ever get
``[CARD]``, ``[CVV]``… The masks tell the agent a number was given without
revealing it — payments belong on a PCI-compliant channel (secure IVR,
payment link).

Masking wraps the STT's ``push_frame`` rather than adding a processor after
it, because pipeline observers (live transcript) see each frame as soon as
the STT pushes it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from api.services.privacy.redaction import redact_text
from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection


def mask_frame(frame: Any, categories: tuple[str, ...]) -> int:
    """Mask a transcription frame in place. Returns how many items were masked."""
    if not isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)):
        return 0
    if not frame.text:
        return 0
    result = redact_text(frame.text, categories)
    if not result.changed:
        return 0
    frame.text = result.text
    return sum(result.counts.values())


def mask_stt_output(stt: Any, categories: Iterable[str]) -> None:
    """Make ``stt`` push masked transcriptions (idempotent)."""
    if getattr(stt, "_nimbora_pii_masking", False):
        return
    categories = tuple(categories)
    original_push = stt.push_frame

    async def push_frame(frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        mask_frame(frame, categories)
        await original_push(frame, direction)

    stt.push_frame = push_frame
    stt._nimbora_pii_masking = True

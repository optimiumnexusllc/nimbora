"""Spoken prompts for the PBX (voice menus), generated with the organization's
own voice and converted to the telephony format the PBX plays natively.
"""

from __future__ import annotations

import io
import wave

import numpy as np

from api.services.pbx.service import PbxRouteError

# The PBX plays ``.wav`` files as 8 kHz, 16-bit, mono PCM (its "slin" format).
PBX_SAMPLE_RATE = 8000
PBX_SOUND_FORMAT = "slin"
MAX_PROMPT_CHARACTERS = 800
MAX_PROMPT_SECONDS = 90


def to_pbx_wav(audio: bytes) -> bytes:
    """Any PCM16 WAV → 8 kHz mono PCM16 WAV (what the PBX plays without
    transcoding). Linear resampling is plenty for speech prompts."""
    with wave.open(io.BytesIO(audio), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    if width != 2:
        raise ValueError("Only 16-bit PCM audio is supported")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != PBX_SAMPLE_RATE and len(samples):
        count = max(1, round(len(samples) * PBX_SAMPLE_RATE / rate))
        positions = np.linspace(0, len(samples) - 1, count)
        samples = np.interp(positions, np.arange(len(samples)), samples)
    pcm = np.clip(np.round(samples), -32768, 32767).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(PBX_SAMPLE_RATE)
        target.writeframes(pcm)
    return output.getvalue()


def wav_duration(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate() or 1)


async def _effective_voice(organization_id: int, voice_workflow_id: int | None):
    """The organization's default models, or those of one of its agents (so
    the menu speaks with the same voice as the agent it hands calls to)."""
    from api.db import db_client
    from api.services.configuration.model_connections import (
        resolve_model_configuration,
    )
    from api.services.configuration.run_model_configuration import (
        get_workflow_model_override,
    )

    override = None
    if voice_workflow_id:
        workflow = await db_client.get_workflow(
            voice_workflow_id, organization_id=organization_id
        )
        if workflow is None:
            raise PbxRouteError("Agent de la voix introuvable", 404)
        definition = getattr(workflow, "released_definition", None)
        override = get_workflow_model_override(
            getattr(definition, "workflow_configurations", None) or {}
        )
    resolved = await resolve_model_configuration(
        organization_id, workflow_override=override
    )
    return resolved.effective


async def synthesize_prompt(
    organization_id: int, text: str, *, voice_workflow_id: int | None = None
) -> bytes:
    """Speak ``text`` with the organization's voice, as a PBX-ready WAV."""
    from api.services.pipecat.audio_config import AudioConfig
    from api.services.pipecat.service_factory import create_tts_service
    from api.services.pipecat.speech_synthesis import synthesize_speech

    text = (text or "").strip()
    if not text:
        raise PbxRouteError("Texte à prononcer manquant", 422)
    if len(text) > MAX_PROMPT_CHARACTERS:
        raise PbxRouteError(
            f"Message trop long ({MAX_PROMPT_CHARACTERS} caractères au plus)", 422
        )
    try:
        user_config = await _effective_voice(organization_id, voice_workflow_id)
    except PbxRouteError:
        raise
    except Exception as error:
        raise PbxRouteError(
            "Aucune voix configurée : choisissez des modèles par défaut dans "
            "« Modèles » avant de générer les messages.",
            409,
        ) from error
    audio_config = AudioConfig(
        transport_in_sample_rate=PBX_SAMPLE_RATE,
        transport_out_sample_rate=PBX_SAMPLE_RATE,
        vad_sample_rate=PBX_SAMPLE_RATE,
        pipeline_sample_rate=PBX_SAMPLE_RATE,
    )
    try:
        tts = create_tts_service(
            user_config, audio_config, organization_id=organization_id
        )
        audio = await synthesize_speech(
            tts,
            text,
            sample_rate=PBX_SAMPLE_RATE,
            max_duration=MAX_PROMPT_SECONDS,
        )
    except Exception as error:
        raise PbxRouteError(
            "La synthèse vocale a échoué : vérifiez la voix configurée "
            f"({type(error).__name__}).",
            502,
        ) from error
    return to_pbx_wav(audio)

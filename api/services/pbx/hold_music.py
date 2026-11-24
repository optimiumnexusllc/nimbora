"""The company's music on hold: music (generated, or its own) and an
announcement spoken with its voice, played in a loop to callers waiting in its
queues and parking lots.

On the PBX it is one music-on-hold class of the company's tenant (label
``LABEL``, mode ``files``, alphabetical order): ``01-musique.wav`` (or
``01-pause.wav`` for an announcement alone) then ``02-annonce.wav``. Its name
replaces ``default`` on the company's queues and parking lots, and on those
created afterwards.

The generated music is computed here (soft chords and a slow arpeggio): it
belongs to nobody, so it needs no licence. No local model generates real
music; the announcement is what the company's voice says.
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from typing import Literal

import numpy as np

from api.services.pbx import prompts
from api.services.pbx.client import PbxClient
from api.services.pbx.service import PbxRouteError, _connection, client_for

LABEL = "nimbora-attente"
MUSIC_FILE = "01-musique.wav"
PAUSE_FILE = "01-pause.wav"
ANNOUNCEMENT_FILE = "02-annonce.wav"
PAUSE_SECONDS = 20
GENERATED_SECONDS = 60
MAX_MUSIC_SECONDS = 600
MAX_UPLOAD_BYTES = 60 * 1024 * 1024
RATE = prompts.PBX_SAMPLE_RATE

ANNOUNCEMENTS = {
    "fr": "Merci de patienter, un conseiller va vous répondre dans un instant.",
    "en": "Thank you for holding, an advisor will be with you shortly.",
    "es": "Gracias por su espera, un asesor le atenderá en un momento.",
    "de": "Bitte haben Sie einen Moment Geduld, ein Berater ist gleich für Sie da.",
    "it": "Grazie per l'attesa, un consulente le risponderà a breve.",
    "pt": "Obrigado por aguardar, um consultor irá atendê-lo em instantes.",
}
LANGUAGE_NAMES = {
    "fr": ("fr", "français", "francais", "french"),
    "en": ("en", "anglais", "english"),
    "es": ("es", "espagnol", "español", "espanol", "spanish"),
    "de": ("de", "allemand", "deutsch", "german"),
    "it": ("it", "italien", "italiano", "italian"),
    "pt": ("pt", "portugais", "português", "portugues", "portuguese"),
}


@dataclass
class HoldMusicSpec:
    music: Literal["generated", "custom", "none"] = "generated"
    announcement: str = ""
    voice_workflow_id: int | None = None
    custom_music: bytes | None = None


def suggested_announcement(languages: list[str]) -> str:
    """In the first language of the company's profile we can write in."""
    for language in languages:
        key = language.strip().lower()
        for code, names in LANGUAGE_NAMES.items():
            if key in names:
                return ANNOUNCEMENTS[code]
    return ANNOUNCEMENTS["fr"]


# ------------------------------------------------------------ the music


def _wav(samples: np.ndarray) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(samples.astype("<i2").tobytes())
    return out.getvalue()


def generate_music(seconds: int = GENERATED_SECONDS) -> bytes:
    """A calm loop for a phone line (8 kHz mono): pads on I–vi–IV–V and a
    slow arpeggio an octave up, where telephones carry sound best."""
    chords = (  # C, A minor, F, G (Hz)
        (261.63, 329.63, 392.00),
        (220.00, 261.63, 329.63),
        (174.61, 220.00, 261.63),
        (196.00, 246.94, 293.66),
    )
    bar = 5.0
    count = int(seconds * RATE)
    t = np.arange(count) / RATE
    signal = np.zeros(count)
    bar_samples = int(bar * RATE)
    local = np.arange(bar_samples) / RATE
    # Raised-cosine swell over the bar: chords fade into each other.
    swell = np.sin(np.pi * local / bar) ** 0.8
    step = bar / 8
    for index, start in enumerate(range(0, count, bar_samples)):
        chord = chords[index % len(chords)]
        end = min(start + bar_samples, count)
        span = t[start:end]
        pad = sum(
            np.sin(2 * np.pi * f * span) + 0.25 * np.sin(4 * np.pi * f * span)
            for f in chord
        )
        signal[start:end] += 0.5 * pad * swell[: end - start]
        for note in range(8):
            onset = start + int(note * step * RATE)
            if onset >= end:
                break
            stop = min(onset + int(1.2 * RATE), count)
            age = np.arange(stop - onset) / RATE
            frequency = 2 * chord[(0, 1, 2, 1)[note % 4]]
            pluck = np.sin(2 * np.pi * frequency * age) * np.exp(-age / 0.35)
            signal[onset:stop] += 0.6 * pluck * np.minimum(age / 0.01, 1.0)
    fade = int(0.25 * RATE)
    ramp = np.linspace(0.0, 1.0, fade)
    signal[:fade] *= ramp
    signal[-fade:] *= ramp[::-1]
    signal *= 0.45 * 32767 / np.abs(signal).max()
    return _wav(np.round(signal))


def _custom_music(audio: bytes) -> bytes:
    try:
        converted = prompts.to_pbx_wav(audio)
    except (wave.Error, EOFError, ValueError) as error:
        raise PbxRouteError(
            "Musique illisible : envoyez un fichier WAV (PCM 16 bits).", 422
        ) from error
    if prompts.wav_duration(converted) > MAX_MUSIC_SECONDS:
        raise PbxRouteError(
            f"Musique trop longue ({MAX_MUSIC_SECONDS // 60} minutes au plus)", 422
        )
    return converted


# -------------------------------------------------------------- the PBX


async def _company_class(client: PbxClient, tenant_uuid: str | None) -> dict | None:
    for moh in await client.mohs():
        if moh.get("label") == LABEL and (
            not tenant_uuid or moh.get("tenant_uuid") == tenant_uuid
        ):
            return moh
    return None


async def class_name(client: PbxClient) -> str:
    """For new queues and parking lots: the company's music, else the engine's."""
    moh = await _company_class(client, client.settings.tenant_uuid)
    return moh["name"] if moh else "default"


async def _play_everywhere(client: PbxClient, name: str, *, only: str | None = None):
    """Queues and parking lots play ``name`` (``only``: those playing it now)."""
    from api.services.pbx.admin import _queue_editable

    for listed in await client.queues():
        queue = await client.queue(listed["id"])
        current = queue.get("music_on_hold") or "default"
        if current != name and (only is None or current == only):
            await client.update_queue(
                queue["id"], {**_queue_editable(queue), "music_on_hold": name}
            )
    for lot in await client.parkinglots():
        current = lot.get("music_on_hold") or "default"
        if current != name and (only is None or current == only):
            await client.update_parkinglot(
                lot["id"],
                {
                    "name": lot.get("name"),
                    "slots_start": lot.get("slots_start"),
                    "slots_end": lot.get("slots_end"),
                    "timeout": lot.get("timeout"),
                    "music_on_hold": name,
                },
            )


async def _state(client: PbxClient, languages: list[str]) -> dict:
    moh = await _company_class(client, client.settings.tenant_uuid)
    files = {f.get("name") for f in (moh or {}).get("files") or []}
    name = moh["name"] if moh else None
    queues = [await client.queue(q["id"]) for q in await client.queues()]
    lots = await client.parkinglots()
    return {
        "active": moh is not None,
        "music": MUSIC_FILE in files,
        "announcement": ANNOUNCEMENT_FILE in files,
        "queues": sum(1 for q in queues if name and q.get("music_on_hold") == name),
        "parking_lots": sum(1 for x in lots if name and x.get("music_on_hold") == name),
        "suggested_announcement": suggested_announcement(languages),
    }


async def _languages(organization_id: int) -> list[str]:
    try:
        from api.services.business.profile import get_business_profile

        return (await get_business_profile(organization_id)).languages
    except Exception:  # noqa: BLE001 - only used to suggest a text
        return []


async def get_hold_music(organization_id: int, **client_kwargs) -> dict:
    connection = await _connection(organization_id)
    languages = await _languages(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        return await _state(client, languages)


async def publish_hold_music(
    organization_id: int, spec: HoldMusicSpec, **client_kwargs
) -> dict:
    announcement = (spec.announcement or "").strip()
    files: dict[str, bytes] = {}
    if spec.music == "generated":
        files[MUSIC_FILE] = generate_music()
    elif spec.music == "custom":
        if not spec.custom_music:
            raise PbxRouteError("Choisissez le fichier de votre musique", 422)
        files[MUSIC_FILE] = _custom_music(spec.custom_music)
    elif announcement:
        files[PAUSE_FILE] = _wav(np.zeros(PAUSE_SECONDS * RATE))
    if announcement:
        files[ANNOUNCEMENT_FILE] = await prompts.synthesize_prompt(
            organization_id, announcement, voice_workflow_id=spec.voice_workflow_id
        )
    if not files:
        raise PbxRouteError("Rien à jouer : choisissez une musique ou une annonce", 422)

    connection = await _connection(organization_id)
    languages = await _languages(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        moh = await _company_class(client, client.settings.tenant_uuid)
        if moh is None:
            moh = await client.create_moh(
                {"label": LABEL, "mode": "files", "sort": "alphabetical"}
            )
        for filename, audio in files.items():
            await client.upload_moh_file(moh["uuid"], filename, audio)
        for stale in moh.get("files") or []:
            if stale.get("name") not in files:
                await client.delete_moh_file(moh["uuid"], stale["name"])
        await _play_everywhere(client, moh["name"])
        return await _state(client, languages)


async def remove_hold_music(organization_id: int, **client_kwargs) -> None:
    """Back to the engine's default music; the company's class is deleted."""
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        moh = await _company_class(client, client.settings.tenant_uuid)
        if moh is None:
            return
        await _play_everywhere(client, "default", only=moh["name"])
        await client.delete_moh(moh["uuid"])

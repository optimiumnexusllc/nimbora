"""Recordings of human calls on the enterprise PBX, kept by NIMBORA.

* **What is recorded** is set once for the company (incoming and outgoing
  external calls, internal calls) and pushed to every extension — or to the
  extensions chosen — as the engine's per-user recording switches.
* **Import**: each finished recorded call (webhook ``call_log_created``, and
  a sweep every 10 minutes as a safety net) is copied to the platform's
  storage, optionally removed from the PBX, and listed in the console.
* **Transcription** uses the organization's own speech recognizer; payment
  data (card numbers, CVV, IBAN, social security numbers) is always masked
  in the stored text, plus every category of the privacy policy.
* **Retention and GDPR**: the privacy policy's recording retention purges
  them, and erasing a customer deletes their recordings.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from api.services.pbx.client import PbxClient, PbxError
from api.services.pbx.service import (
    PbxRouteError,
    _ai_phone_rows,
    _connection,
    _human_call_interaction,
    _routed_numbers,
    client_for,
)

PCI_CATEGORIES = ("card", "cvv", "iban", "ssn")
# Speech recognizers mishear digits: a 13–19 digit run that fails the card
# checksum is still treated as a card number in human call transcripts.
_LONG_DIGITS = re.compile(r"(?<![\d\[])(?:\d[ .\-]?){12,18}\d(?![\d\]])")


def mask_card_like(text: str) -> str:
    return _LONG_DIGITS.sub("[CARD]", text)


def _is_ai_call(cdr: dict, routed: dict) -> bool:
    from api.services.customer_memory.service import normalize_phone

    return any(
        number and (normalize_phone(number) or number) in routed
        for number in (cdr.get("requested_extension"), cdr.get("destination_extension"))
    )


SYNC_WINDOW = timedelta(days=2)
MAX_RECORDING_BYTES = 200 * 1024 * 1024
RECORD_FIELDS = {
    "incoming_external": "call_record_incoming_external_enabled",
    "outgoing_external": "call_record_outgoing_external_enabled",
    "incoming_internal": "call_record_incoming_internal_enabled",
    "outgoing_internal": "call_record_outgoing_internal_enabled",
}


class RecordingPolicy(BaseModel):
    # What the PBX records (pushed to the extensions).
    incoming_external: bool = False
    outgoing_external: bool = False
    internal: bool = False
    # None: every extension; otherwise only these (others stop recording).
    user_uuids: list[str] | None = Field(default=None, max_length=1000)
    # What NIMBORA does with the recordings.
    import_enabled: bool = True
    transcribe: bool = False
    remove_from_pbx: bool = False

    @property
    def records_anything(self) -> bool:
        return self.incoming_external or self.outgoing_external or self.internal

    def user_flags(self, selected: bool) -> dict[str, bool]:
        on = {
            "incoming_external": self.incoming_external,
            "outgoing_external": self.outgoing_external,
            "incoming_internal": self.internal,
            "outgoing_internal": self.internal,
        }
        return {RECORD_FIELDS[k]: (v and selected) for k, v in on.items()}


def policy_of(connection) -> RecordingPolicy:
    try:
        return RecordingPolicy.model_validate(connection.recording_policy or {})
    except ValueError:
        return RecordingPolicy()


async def save_policy(
    organization_id: int, policy: RecordingPolicy, **client_kwargs
) -> dict[str, Any]:
    """Store the policy and switch recording on or off on the extensions."""
    from api.db import db_client

    connection = await _connection(organization_id)
    selected = set(policy.user_uuids or [])
    changed = 0
    async with client_for(connection, **client_kwargs) as client:
        users = await client.users()
        known = {u.get("uuid") for u in users}
        if policy.user_uuids is not None and selected - known:
            raise PbxRouteError("Poste introuvable", 404)
        for user in users:
            uuid = user.get("uuid")
            flags = policy.user_flags(policy.user_uuids is None or uuid in selected)
            current = await client.user(uuid)
            if all(bool(current.get(k)) == v for k, v in flags.items()):
                continue
            await client.update_user(uuid, flags)
            changed += 1
    await db_client.save_pbx_connection(
        organization_id, {"recording_policy": policy.model_dump()}
    )
    return {"policy": policy.model_dump(), "extensions_changed": changed}


# ------------------------------------------------------------- import


def _storage():
    from api.services.storage import get_current_storage_backend, storage_fs

    return storage_fs, get_current_storage_backend().value


def _storage_for(backend: str):
    from api.services.storage import get_storage_for_backend

    return get_storage_for_backend(backend)


async def _transcribe(organization_id: int, audio: bytes) -> tuple[str | None, str]:
    """(masked transcript, status). Never raises."""
    from api.services.configuration.model_connections import (
        resolve_model_configuration,
    )
    from api.services.privacy.redaction import redact_text
    from api.services.privacy.service import get_privacy_settings
    from api.services.whatsapp_messaging.transcribe import (
        TranscriptionUnavailable,
        transcribe_voice_note,
    )

    try:
        resolved = await resolve_model_configuration(organization_id)
        text = await transcribe_voice_note(audio, "audio/wav", resolved.effective.stt)
    except TranscriptionUnavailable:
        return None, "unavailable"
    except Exception:
        logger.opt(exception=True).warning("PBX recording transcription failed")
        return None, "failed"
    settings = await get_privacy_settings(organization_id)
    categories = set(PCI_CATEGORIES)
    if settings.redaction_enabled:
        categories |= set(settings.categories)
    return redact_text(mask_card_like(text), categories).text, "done"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def import_recording(
    connection, client: PbxClient, cdr: dict, recording: dict, policy: RecordingPolicy
):
    """Copy one recording into NIMBORA (idempotent)."""
    from api.db import db_client

    organization_id = connection.organization_id
    uuid = str(recording.get("uuid") or "")
    if not uuid or recording.get("deleted"):
        return None
    if await db_client.known_pbx_recording_uuids(organization_id, [uuid]):
        return None
    audio = await client.recording_media(cdr["id"], uuid)
    if not audio or len(audio) > MAX_RECORDING_BYTES:
        logger.warning(f"[PBX org={organization_id}] Recording {uuid} skipped (size)")
        return None
    storage, backend = _storage()
    started = _parse_time(recording.get("start_time")) or _parse_time(cdr.get("start"))
    day = (started or datetime.now(UTC)).strftime("%Y/%m/%d")
    key = f"pbx-recordings/{organization_id}/{day}/{cdr['id']}-{uuid}.wav"
    if not await storage.acreate_file_from_bytes(key, audio):
        raise PbxError("Stockage de l'enregistrement impossible")
    ended = _parse_time(recording.get("end_time"))
    duration = (
        int((ended - started).total_seconds())
        if started and ended
        else int(float(cdr.get("duration") or 0)) or None
    )
    phone, _ = _human_call_interaction(cdr)
    transcript, status = (None, "none")
    if policy.transcribe:
        transcript, status = await _transcribe(organization_id, audio)
    direction = (cdr.get("call_direction") or cdr.get("call_drection") or "").lower()
    row = await db_client.create_pbx_recording(
        organization_id,
        {
            "cdr_id": int(cdr["id"]),
            "recording_uuid": uuid,
            "started_at": started,
            "duration_seconds": duration,
            "direction": direction or None,
            "source": (cdr.get("source_extension") or None)
            and str(cdr["source_extension"])[:64],
            "source_name": (cdr.get("source_name") or None)
            and str(cdr["source_name"])[:128],
            "destination": (
                cdr.get("destination_extension")
                or cdr.get("requested_extension")
                or None
            )
            and str(cdr.get("destination_extension") or cdr.get("requested_extension"))[
                :64
            ],
            "destination_name": (cdr.get("destination_name") or None)
            and str(cdr["destination_name"])[:128],
            "customer_phone": phone,
            "storage_backend": backend,
            "storage_key": key,
            "size_bytes": len(audio),
            "transcript": transcript,
            "transcript_status": status,
        },
    )
    if policy.remove_from_pbx:
        try:
            await client.delete_recording_media(cdr["id"], uuid)
            await db_client.update_pbx_recording(
                organization_id, row.id, {"removed_from_pbx": True}
            )
        except PbxError:
            logger.opt(exception=True).warning("Recording kept on the PBX")
    return row


async def import_cdr(connection, cdr: dict, **client_kwargs) -> int:
    """Import every recording of one call log. Returns how many were added."""
    policy = policy_of(connection)
    if not policy.import_enabled or not cdr.get("recordings"):
        return 0
    # AI calls are recorded by the agent run itself.
    routed = _routed_numbers(await _ai_phone_rows(connection))
    if _is_ai_call(cdr, routed):
        return 0
    added = 0
    async with client_for(connection, **client_kwargs) as client:
        for recording in cdr.get("recordings") or []:
            if await import_recording(connection, client, cdr, recording, policy):
                added += 1
    return added


async def sync_recordings(organization_id: int, **client_kwargs) -> dict[str, int]:
    """Import the recordings of the last two days that NIMBORA does not have."""
    from api.db import db_client

    connection = await _connection(organization_id)
    policy = policy_of(connection)
    if not policy.import_enabled:
        return {"imported": 0, "seen": 0}
    since = (datetime.now(UTC) - SYNC_WINDOW).isoformat(timespec="seconds")
    imported = seen = 0
    routed = _routed_numbers(await _ai_phone_rows(connection))
    async with client_for(connection, **client_kwargs) as client:
        for cdr in await client.recorded_cdr(limit=200, since=since):
            if _is_ai_call(cdr, routed):
                continue
            uuids = [
                str(r.get("uuid")) for r in cdr.get("recordings") or [] if r.get("uuid")
            ]
            known = await db_client.known_pbx_recording_uuids(organization_id, uuids)
            for recording in cdr.get("recordings") or []:
                seen += 1
                if str(recording.get("uuid")) in known:
                    continue
                try:
                    if await import_recording(
                        connection, client, cdr, recording, policy
                    ):
                        imported += 1
                except PbxError:
                    logger.opt(exception=True).warning("Recording import failed")
    await db_client.save_pbx_connection(
        organization_id, {"recordings_synced_at": datetime.now(UTC)}
    )
    return {"imported": imported, "seen": seen}


async def import_pbx_recordings(_ctx, organization_id: int, cdr: dict) -> int:
    """arq job queued by the call-log webhook."""
    connection = await _connection(organization_id)
    return await import_cdr(connection, cdr)


async def sync_all_recordings(_ctx=None) -> dict[str, int]:
    """arq cron: catch up on recordings whose webhook was missed."""
    from api.db import db_client

    totals = {"organizations": 0, "imported": 0}
    for connection in await db_client.list_pbx_connections():
        if not policy_of(connection).import_enabled or not (
            connection.recording_policy or {}
        ):
            continue
        try:
            result = await sync_recordings(connection.organization_id)
            totals["organizations"] += 1
            totals["imported"] += result["imported"]
        except Exception:
            logger.opt(exception=True).warning(
                f"[PBX org={connection.organization_id}] Recording sync failed"
            )
    return totals


# ------------------------------------------------------- console & GDPR


def serialize(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "cdr_id": row.cdr_id,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "duration_seconds": row.duration_seconds,
        "direction": row.direction,
        "source": row.source,
        "source_name": row.source_name,
        "destination": row.destination,
        "destination_name": row.destination_name,
        "customer_phone": row.customer_phone,
        "size_bytes": row.size_bytes,
        "transcript": row.transcript,
        "transcript_status": row.transcript_status,
        "removed_from_pbx": bool(row.removed_from_pbx),
    }


async def audio_url(organization_id: int, recording_id: int) -> str:
    from api.db import db_client

    row = await db_client.get_pbx_recording(organization_id, recording_id)
    if row is None:
        raise PbxRouteError("Enregistrement introuvable", 404)
    url = await _storage_for(row.storage_backend).aget_signed_url(
        row.storage_key, expiration=900, force_inline=True
    )
    if not url:
        raise PbxRouteError("Fichier audio indisponible", 404)
    return url


async def delete_recording(organization_id: int, recording_id: int) -> bool:
    from api.db import db_client

    row = await db_client.get_pbx_recording(organization_id, recording_id)
    if row is None:
        return False
    try:
        await _storage_for(row.storage_backend).adelete_file(row.storage_key)
    except Exception:
        logger.opt(exception=True).warning("Recording file not deleted")
    return await db_client.delete_pbx_recording(organization_id, recording_id)


async def purge_before(organization_id: int, before: datetime) -> int:
    """Retention: delete recordings of calls older than ``before``."""
    from api.db import db_client

    removed = 0
    while True:
        rows = await db_client.list_pbx_recordings_before(organization_id, before)
        if not rows:
            return removed
        for row in rows:
            if await delete_recording(organization_id, row.id):
                removed += 1
        if len(rows) < 200:
            return removed


async def erase_for_phone(organization_id: int, phone: str) -> int:
    """GDPR erasure: every recording with this customer."""
    from api.db import db_client
    from api.services.customer_memory.service import normalize_phone

    normalized = normalize_phone(phone)
    if not normalized:
        return 0
    spellings = sorted(
        {normalized, normalized.lstrip("+"), f"+{normalized.lstrip('+')}"}
    )
    removed = 0
    for row in await db_client.list_pbx_recordings_for_phone(
        organization_id, spellings
    ):
        if await delete_recording(organization_id, row.id):
            removed += 1
    return removed

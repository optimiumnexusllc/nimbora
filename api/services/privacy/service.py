"""GDPR toolkit: redaction policy, right to be forgotten, access, retention.

Per-organization settings (``PRIVACY`` configuration) decide:

* **redaction**: which personal data categories are masked in everything
  NIMBORA keeps about a call (transcript file, run logs, AI handoff cards,
  customer memory summaries, optionally extracted variables);
* **PCI masking in conversation**: card numbers, CVV, IBAN and social
  security numbers are masked before the LLM ever sees them;
* **recordings**: keep audio or not at all;
* **retention**: recordings, transcripts and customer memory are purged
  after N days by a daily sweep (call metadata and billing stay).

Erasure (art. 17) and export (art. 15) work from the person's phone
number and are recorded in a register that never stores the number in clear.
"""

from __future__ import annotations

import hashlib
import hmac
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, field_validator

from api.enums import OrganizationConfigurationKey
from api.services.privacy.redaction import (
    ALL_CATEGORIES,
    CONVERSATION_CATEGORIES,
    redact_text,
    redact_value,
)

SETTING_KEY = OrganizationConfigurationKey.PRIVACY.value
ERASED = "[ERASED]"
# Run fields that are call plumbing, not personal data.
_TECHNICAL_KEYS = frozenset(
    {
        "provider",
        "direction",
        "telephony_configuration_id",
        "workflow_uuid",
        "trigger_mode",
        "call_id",
        "stream_sid",
        "call_language",
        "languages_spoken",
        "call_disposition",
        "mapped_call_disposition",
    }
)


class PrivacySettings(BaseModel):
    redaction_enabled: bool = False
    categories: list[str] = Field(default_factory=lambda: list(ALL_CATEGORIES))
    mask_in_conversation: bool = False
    redact_extracted_data: bool = False
    store_recordings: bool = True
    recording_retention_days: int | None = Field(default=None, ge=1, le=3650)
    transcript_retention_days: int | None = Field(default=None, ge=1, le=3650)
    customer_memory_retention_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("categories")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        unknown = [c for c in value if c not in ALL_CATEGORIES]
        if unknown:
            raise ValueError(f"Unknown categories: {', '.join(unknown)}")
        return list(dict.fromkeys(value))

    @property
    def conversation_categories(self) -> tuple[str, ...]:
        return CONVERSATION_CATEGORIES if self.mask_in_conversation else ()


async def get_privacy_settings(organization_id: int | None) -> PrivacySettings:
    if not organization_id:
        return PrivacySettings()
    from api.db import db_client

    try:
        value = await db_client.get_configuration_value(organization_id, SETTING_KEY)
        return PrivacySettings.model_validate(value or {})
    except Exception:
        logger.opt(exception=True).warning("Invalid privacy settings; using defaults")
        return PrivacySettings()


async def save_privacy_settings(
    organization_id: int, settings: PrivacySettings
) -> PrivacySettings:
    from api.db import db_client

    await db_client.upsert_configuration(
        organization_id, SETTING_KEY, settings.model_dump()
    )
    return settings


# ----------------------------------------------------------- redaction use


def redact_for_storage(text: str | None, settings: PrivacySettings) -> str | None:
    if not text or not settings.redaction_enabled:
        return text
    return redact_text(text, settings.categories).text


def redact_value_for_storage(value: Any, settings: PrivacySettings) -> Any:
    if not settings.redaction_enabled:
        return value
    return redact_value(value, settings.categories, skip_keys=_TECHNICAL_KEYS)


def redact_run_logs(
    logs: dict[str, Any], settings: PrivacySettings
) -> tuple[dict[str, Any], dict[str, int]]:
    """Mask transcripts kept in the run's logs. Idempotent (marker)."""
    if not settings.redaction_enabled or not isinstance(logs, dict):
        return logs, {}
    if (logs.get("privacy") or {}).get("redacted"):
        return logs, {}
    counts: Counter = Counter()
    updated = dict(logs)
    for key in ("realtime_feedback_events", "transcript", "final_extraction"):
        if key in updated:
            updated[key] = redact_value(updated[key], settings.categories, counts)
    updated["privacy"] = {
        "redacted": True,
        "categories": list(settings.categories),
        "counts": dict(counts),
    }
    return updated, dict(counts)


def redact_gathered_context(
    gathered: dict[str, Any], settings: PrivacySettings
) -> dict[str, Any]:
    if not settings.redaction_enabled or not settings.redact_extracted_data:
        return gathered
    return redact_value(gathered, settings.categories, skip_keys=_TECHNICAL_KEYS)


async def apply_privacy_to_completed_run(workflow_run, organization_id: int) -> bool:
    """Completion-time pass (all channels): mask what the call left in the DB."""
    from api.db import db_client

    settings = await get_privacy_settings(organization_id)
    if not settings.redaction_enabled:
        return False
    logs, counts = redact_run_logs(dict(workflow_run.logs or {}), settings)
    fields: dict[str, Any] = {}
    if logs is not workflow_run.logs and logs != (workflow_run.logs or {}):
        fields["logs"] = logs
    gathered = redact_gathered_context(
        dict(workflow_run.gathered_context or {}), settings
    )
    if gathered != (workflow_run.gathered_context or {}):
        fields["gathered_context"] = gathered
    if not fields:
        return False
    await db_client.scrub_workflow_run(organization_id, workflow_run.id, fields)
    for name, value in fields.items():
        setattr(workflow_run, name, value)
    if counts:
        logger.info(f"[privacy] Run {workflow_run.id}: masked {counts}")
    return True


# ---------------------------------------------------------------- subjects


def _subject_suffix(phone: str) -> str:
    from api.services.customer_memory.service import normalize_phone, phone_suffix

    normalized = normalize_phone(phone)
    if not normalized:
        raise ValueError("A valid phone number is required")
    return phone_suffix(normalized)


def subject_hash(organization_id: int, suffix: str) -> str:
    from api.constants import OSS_JWT_SECRET

    key = f"{OSS_JWT_SECRET or 'nimbora'}:privacy:{organization_id}".encode()
    return hmac.new(key, suffix.encode(), hashlib.sha256).hexdigest()


def subject_hint(suffix: str) -> str:
    return "•" * 6 + suffix[-3:]


async def _delete_run_artifacts(run) -> int:
    """Delete a run's recordings and transcript files. Returns files removed."""
    from api.services.storage import get_storage_for_backend

    keys: list[str] = []
    if run.recording_url:
        keys.append(run.recording_url)
    for meta in ((run.extra or {}).get("recordings") or {}).values():
        if isinstance(meta, dict) and meta.get("storage_key"):
            keys.append(meta["storage_key"])
    if run.transcript_url:
        keys.append(run.transcript_url)
    if not keys:
        return 0
    try:
        storage = get_storage_for_backend(run.storage_backend)
    except Exception:
        logger.warning(f"[privacy] Unknown storage backend for run {run.id}")
        return 0
    removed = 0
    for key in dict.fromkeys(keys):
        if await storage.adelete_file(key):
            removed += 1
        else:
            logger.warning(f"[privacy] Could not delete {key} (run {run.id})")
    return removed


def _erased_context(context: dict | None) -> dict:
    return {
        k: v
        for k, v in (context or {}).items()
        if k in _TECHNICAL_KEYS and not isinstance(v, (dict, list))
    } | {"privacy_erased": True}


async def erase_subject(
    organization_id: int, phone: str, *, requested_by: int | None = None
):
    """Right to be forgotten: everything tied to this phone number."""
    from api.db import db_client

    suffix = _subject_suffix(phone)
    request = await db_client.create_privacy_request(
        organization_id=organization_id,
        kind="erasure",
        subject_hash=subject_hash(organization_id, suffix),
        subject_hint=subject_hint(suffix),
        status="running",
        counts={},
        requested_by=requested_by,
    )
    counts: Counter = Counter()
    try:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        for run in await db_client.list_runs_for_phone_suffix(organization_id, suffix):
            counts["files"] += await _delete_run_artifacts(run)
            extra = dict(run.extra or {})
            extra.pop("recordings", None)
            extra["privacy"] = {**(extra.get("privacy") or {}), "erased_at": now}
            await db_client.scrub_workflow_run(
                organization_id,
                run.id,
                {
                    "initial_context": _erased_context(run.initial_context),
                    "gathered_context": _erased_context(run.gathered_context),
                    "logs": {"privacy": {"erased_at": now}},
                    "annotations": {},
                    "recording_url": None,
                    "transcript_url": None,
                    "extra": extra,
                },
            )
            counts["calls"] += 1
        for profile in await db_client.list_customer_profiles_for_suffix(
            organization_id, suffix
        ):
            await db_client.delete_customer_profile(organization_id, profile.id)
            counts["customer_profiles"] += 1
        counts["handoffs"] += await db_client.delete_handoffs_for_suffix(
            organization_id, suffix
        )
        counts["callbacks"] += await db_client.delete_callbacks_for_suffix(
            organization_id, suffix
        )
        from api.services.pbx.recordings import erase_for_phone

        removed = await erase_for_phone(organization_id, phone)
        if removed:
            counts["human_call_recordings"] += removed
        return await db_client.update_privacy_request(
            organization_id,
            request.id,
            {
                "status": "done",
                "counts": dict(counts),
                "completed_at": datetime.now(UTC),
            },
        )
    except Exception as exc:
        logger.opt(exception=True).error("[privacy] Erasure failed")
        await db_client.update_privacy_request(
            organization_id,
            request.id,
            {"status": "failed", "counts": dict(counts), "error": str(exc)[:500]},
        )
        raise


def _iso(value) -> str | None:
    return value.isoformat() if value else None


async def export_subject(
    organization_id: int, phone: str, *, requested_by: int | None = None
) -> dict[str, Any]:
    """Right of access: what the organization holds about this number."""
    from api.db import db_client
    from api.services.customer_memory.service import profile_to_dict

    suffix = _subject_suffix(phone)
    profiles = await db_client.list_customer_profiles_for_suffix(
        organization_id, suffix
    )
    profile_data = []
    for profile in profiles:
        interactions = await db_client.list_customer_interactions(
            organization_id, profile.id, limit=500
        )
        profile_data.append(
            {
                **profile_to_dict(profile),
                "interactions": [
                    {
                        "date": _iso(i.created_at),
                        "direction": i.direction,
                        "agent": i.agent_name,
                        "summary": i.summary,
                        "sentiment": i.sentiment,
                        "outcome": i.outcome,
                    }
                    for i in interactions
                ],
            }
        )
    runs = await db_client.list_runs_for_phone_suffix(organization_id, suffix)
    calls = [
        {
            "id": run.id,
            "date": _iso(run.created_at),
            "channel": run.mode,
            "direction": (run.initial_context or {}).get("direction"),
            "agent_id": run.workflow_id,
            "duration_seconds": (run.usage_info or {}).get("call_duration_seconds"),
            "recording_kept": bool(run.recording_url),
            "transcript_kept": bool(run.transcript_url),
            "collected_data": {
                k: v
                for k, v in (run.gathered_context or {}).items()
                if not k.startswith(("_", "mps_"))
            },
        }
        for run in runs
    ]
    handoffs = [
        {
            "date": _iso(h.created_at),
            "queue": h.queue_slug,
            "reason": h.reason,
            "summary": h.summary,
        }
        for h in await db_client.list_handoffs_for_suffix(organization_id, suffix)
    ]
    callbacks = [
        {
            "scheduled_at": _iso(c.scheduled_at),
            "status": c.status,
            "reason": c.reason,
            "outcome": c.outcome,
        }
        for c in await db_client.list_callbacks_for_suffix(organization_id, suffix)
    ]
    from api.services.customer_memory.service import normalize_phone

    normalized = normalize_phone(phone) or ""
    human_calls = [
        {
            "date": _iso(r.started_at),
            "direction": r.direction,
            "with": r.destination_name if r.direction == "inbound" else r.source_name,
            "duration_seconds": r.duration_seconds,
            "recording_kept": True,
            "transcript": r.transcript,
        }
        for r in await db_client.list_pbx_recordings_for_phone(
            organization_id,
            sorted({normalized, normalized.lstrip("+"), f"+{normalized.lstrip('+')}"}),
        )
    ]
    counts = {
        "customer_profiles": len(profile_data),
        "calls": len(calls),
        "handoffs": len(handoffs),
        "callbacks": len(callbacks),
        "human_call_recordings": len(human_calls),
    }
    await db_client.create_privacy_request(
        organization_id=organization_id,
        kind="export",
        subject_hash=subject_hash(organization_id, suffix),
        subject_hint=subject_hint(suffix),
        status="done",
        counts=counts,
        requested_by=requested_by,
        completed_at=datetime.now(UTC),
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "subject": {"phone_ending": suffix[-3:]},
        "summary": counts,
        "customer_profiles": profile_data,
        "calls": calls,
        "handoffs": handoffs,
        "callbacks": callbacks,
        "human_call_recordings": human_calls,
        "notes": (
            "Recordings and transcripts are available on request; this export "
            "lists whether each call still holds them."
        ),
    }


# --------------------------------------------------------------- retention


async def purge_run(run, organization_id: int, kind: str, now: datetime) -> int:
    """Remove a run's recording or transcript, keep metadata and billing."""
    from api.db import db_client
    from api.services.storage import get_storage_for_backend

    extra = dict(run.extra or {})
    privacy = dict(extra.get("privacy") or {})
    fields: dict[str, Any] = {}
    removed = 0
    try:
        storage = get_storage_for_backend(run.storage_backend)
    except Exception:
        storage = None
    if kind == "recording":
        keys = [run.recording_url] if run.recording_url else []
        keys += [
            m["storage_key"]
            for m in (extra.get("recordings") or {}).values()
            if isinstance(m, dict) and m.get("storage_key")
        ]
        for key in dict.fromkeys(keys):
            if storage is not None and await storage.adelete_file(key):
                removed += 1
        extra.pop("recordings", None)
        fields["recording_url"] = None
    else:
        if run.transcript_url and storage is not None:
            if await storage.adelete_file(run.transcript_url):
                removed += 1
        logs = dict(run.logs or {})
        for key in ("realtime_feedback_events", "transcript", "final_extraction"):
            logs.pop(key, None)
        fields["transcript_url"] = None
        fields["logs"] = logs
    privacy[f"{kind}_purged_at"] = now.isoformat(timespec="seconds")
    extra["privacy"] = privacy
    fields["extra"] = extra
    await db_client.scrub_workflow_run(organization_id, run.id, fields)
    return removed


async def apply_retention(
    organization_id: int, settings: PrivacySettings, now: datetime | None = None
) -> dict[str, int]:
    from api.db import db_client

    now = now or datetime.now(UTC)
    counts: Counter = Counter()
    for kind, days in (
        ("recording", settings.recording_retention_days),
        ("transcript", settings.transcript_retention_days),
    ):
        if not days:
            continue
        before = now - timedelta(days=days)
        while True:
            runs = await db_client.list_runs_with_artifacts_before(
                organization_id, before, kind, limit=200
            )
            if not runs:
                break
            for run in runs:
                counts["files"] += await purge_run(run, organization_id, kind, now)
                counts[f"{kind}s"] += 1
            if len(runs) < 200:
                break
    if settings.recording_retention_days:
        from api.services.pbx.recordings import purge_before

        removed = await purge_before(
            organization_id, now - timedelta(days=settings.recording_retention_days)
        )
        if removed:
            counts["human_call_recordings"] += removed
    if settings.customer_memory_retention_days:
        before = now - timedelta(days=settings.customer_memory_retention_days)
        counts["interactions"] += await db_client.delete_customer_interactions_before(
            organization_id, before
        )
        counts[
            "customer_profiles"
        ] += await db_client.delete_customer_profiles_inactive_since(
            organization_id, before
        )
    return dict(counts)


async def run_retention_sweep(_ctx=None) -> dict[str, int]:
    """arq cron entry point (daily): apply every organization's retention."""
    from api.db import db_client

    totals: Counter = Counter()
    for organization_id, value in await db_client.list_organizations_with_configuration(
        SETTING_KEY
    ):
        try:
            settings = PrivacySettings.model_validate(value or {})
            if not (
                settings.recording_retention_days
                or settings.transcript_retention_days
                or settings.customer_memory_retention_days
            ):
                continue
            counts = await apply_retention(organization_id, settings)
            if counts:
                logger.info(f"[privacy] Retention for org {organization_id}: {counts}")
            totals.update(counts)
        except Exception:
            logger.opt(exception=True).warning(
                f"[privacy] Retention failed for org {organization_id}"
            )
    return dict(totals)


# ---------------------------------------------------------- application logs


def redact_log_record(record: dict) -> None:
    """loguru patcher: never write card numbers, IBANs, e-mails… to logs."""
    message = record.get("message")
    if not message:
        return
    result = redact_text(message, ALL_CATEGORIES)
    if result.counts:
        record["message"] = result.text

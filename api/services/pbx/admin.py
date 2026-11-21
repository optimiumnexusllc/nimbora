"""Administer the enterprise PBX from NIMBORA: extensions, agents, queues,
overflow to AI agents, opening hours synced from the business profile.
"""

from __future__ import annotations

import csv
import io
import re
import secrets
import string
from dataclasses import dataclass, field
from typing import Any, Literal

from api.services.branding import brand
from api.services.pbx.client import PbxClient, PbxError
from api.services.pbx.service import (
    PbxRouteError,
    _connection,
    client_for,
)

EXTEN = re.compile(r"^[0-9]{2,10}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AI_KEY_PREFIX = "nimbora-"
OVERFLOW_METADATA_KEY = "pbx_overflow"
AFTER_HOURS_METADATA_KEY = "pbx_after_hours"
SCHEDULE_NAME_PREFIX = "nimbora-horaires"
STRATEGIES = {
    "ringall": "Tous les postes en même temps",
    "leastrecent": "Le conseiller libre depuis le plus longtemps",
    "fewestcalls": "Le conseiller qui a pris le moins d'appels",
    "rrmemory": "Chacun son tour",
    "random": "Au hasard",
    "linear": "Dans l'ordre de la liste",
}
DAY_NUMBERS = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}


def _secret(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _pin(length: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())[:28] or "file"


# ------------------------------------------------------------ extensions


@dataclass
class NewExtension:
    firstname: str
    lastname: str = ""
    extension: str = ""
    email: str | None = None
    line: Literal["sip", "webrtc"] = "sip"
    voicemail: bool = True
    agent: bool = False
    language: str = "fr_FR"
    errors: list[str] = field(default_factory=list)

    def validate(self) -> "NewExtension":
        self.firstname = self.firstname.strip()
        self.lastname = (self.lastname or "").strip()
        self.extension = (self.extension or "").strip()
        self.email = (self.email or "").strip() or None
        if not self.firstname:
            self.errors.append("Prénom manquant")
        if not EXTEN.match(self.extension):
            self.errors.append("Poste invalide (2 à 10 chiffres)")
        if self.email and not EMAIL.match(self.email):
            self.errors.append("E-mail invalide")
        if self.line not in ("sip", "webrtc"):
            self.errors.append("Type de ligne : sip ou webrtc")
        return self


async def _internal_context(client: PbxClient) -> str:
    contexts = await client.contexts("internal")
    if not contexts:
        raise PbxRouteError("Aucun contexte interne sur le PBX", 409)
    return contexts[0]["name"]


async def _templates_for(client: PbxClient, line: str) -> list[dict]:
    templates = await client.sip_templates()
    by_label = {(t.get("label") or "").lower(): t for t in templates}
    chosen = [by_label.get("global")]
    if line == "webrtc":
        # The browser softphone needs the WebRTC template (DTLS, ICE, opus).
        chosen.insert(0, by_label.get("webrtc"))
        if chosen[0] is None:
            raise PbxRouteError("Modèle SIP « webrtc » absent du PBX", 409)
    return [{"uuid": t["uuid"]} for t in chosen if t]


def _user_body(
    spec: NewExtension, context: str, templates: list[dict], creds: dict
) -> dict:
    body: dict[str, Any] = {
        "firstname": spec.firstname,
        "lastname": spec.lastname,
        "language": spec.language,
        "lines": [
            {
                "context": context,
                "extensions": [{"exten": spec.extension, "context": context}],
                "endpoint_sip": {
                    "label": f"{spec.firstname} {spec.lastname}".strip()[:128],
                    "templates": templates,
                    "auth_section_options": [
                        ["username", creds["sip_username"]],
                        ["password", creds["sip_password"]],
                    ],
                },
            }
        ],
        "auth": {
            "username": creds["login"],
            "password": creds["login_password"],
            "enabled": True,
            "purpose": "user",
        },
    }
    if spec.email:
        body["email"] = spec.email
        body["auth"]["email_address"] = spec.email
    if spec.voicemail:
        body["voicemail"] = {
            "name": f"{spec.firstname} {spec.lastname}".strip(),
            "number": spec.extension,
            "context": context,
            "password": creds["voicemail_pin"],
            "email": spec.email,
            "language": spec.language,
            "attach_audio": bool(spec.email),
        }
    return body


async def create_extension(
    organization_id: int, spec: NewExtension, **client_kwargs
) -> dict[str, Any]:
    """User + line + extension + SIP account + voicemail + login (+ agent).

    Secrets are generated here and returned once; the PBX keeps them.
    """
    spec.validate()
    if spec.errors:
        raise PbxRouteError("; ".join(spec.errors), 422)
    connection = await _connection(organization_id)
    creds = {
        "sip_username": f"{_slug(spec.firstname)[:8]}{_pin(4)}",
        "sip_password": _secret(20),
        "login": spec.email or f"poste{spec.extension}",
        "login_password": _secret(14),
        "voicemail_pin": _pin(6) if spec.voicemail else None,
    }
    async with client_for(connection, **client_kwargs) as client:
        context = await _internal_context(client)
        if await client.extensions(exten=spec.extension, context=context):
            raise PbxRouteError(f"Le poste {spec.extension} existe déjà", 409)
        templates = await _templates_for(client, spec.line)
        user = await client.create_user(_user_body(spec, context, templates, creds))
        agent = None
        if spec.agent:
            try:
                agent = await client.create_agent(
                    spec.extension, spec.firstname, spec.lastname
                )
                await client.associate_user_agent(user["uuid"], agent["id"])
            except PbxError:
                # Leave nothing half-made: the extension without its agent.
                if agent:
                    await client.delete_agent(agent["id"])
                await client.delete_user(user["uuid"])
                raise
    return {
        "uuid": user["uuid"],
        "name": f"{spec.firstname} {spec.lastname}".strip(),
        "extension": spec.extension,
        "context": context,
        "line": spec.line,
        "agent_id": agent["id"] if agent else None,
        "credentials": creds,
    }


async def delete_extension(
    organization_id: int, user_uuid: str, **client_kwargs
) -> None:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        await client.delete_user(user_uuid)


async def send_password_reset(
    organization_id: int, login: str, **client_kwargs
) -> None:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        await client.send_password_reset_email(login)


# ---------------------------------------------------------- CSV import

CSV_COLUMNS = ["prenom", "nom", "poste", "email", "ligne", "messagerie", "agent"]
_TRUE = {"oui", "yes", "true", "1", "o", "x"}


def parse_csv(content: str) -> list[NewExtension]:
    """Rows of a CSV (comma or semicolon) into validated extensions."""
    sample = content[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(content.lstrip("﻿")), delimiter=delimiter)
    headers = {(h or "").strip().lower(): h for h in reader.fieldnames or []}
    aliases = {
        "prenom": ["prenom", "prénom", "firstname", "first_name"],
        "nom": ["nom", "lastname", "last_name"],
        "poste": ["poste", "extension", "exten", "numero", "numéro"],
        "email": ["email", "e-mail", "courriel"],
        "ligne": ["ligne", "line", "type"],
        "messagerie": ["messagerie", "voicemail"],
        "agent": ["agent", "centre d'appels"],
    }

    def column(row, name):
        for alias in aliases[name]:
            if alias in headers:
                return (row.get(headers[alias]) or "").strip()
        return ""

    rows = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        line = column(row, "ligne").lower() or "sip"
        rows.append(
            NewExtension(
                firstname=column(row, "prenom"),
                lastname=column(row, "nom"),
                extension=column(row, "poste"),
                email=column(row, "email") or None,
                line="webrtc"
                if line in {"webrtc", "navigateur", "softphone"}
                else line,
                voicemail=(column(row, "messagerie").lower() or "oui") in _TRUE,
                agent=column(row, "agent").lower() in _TRUE,
            ).validate()
        )
    if len(rows) > 500:
        raise PbxRouteError("500 lignes au maximum par import", 422)
    return rows


async def preview_import(
    organization_id: int, content: str, **client_kwargs
) -> list[dict]:
    rows = parse_csv(content)
    seen: dict[str, int] = {}
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        context = await _internal_context(client)
        existing = {e.get("exten") for e in await client.extensions(context=context)}
    report = []
    for index, row in enumerate(rows, start=2):  # line 1 = headers
        errors = list(row.errors)
        if row.extension in existing:
            errors.append(f"Le poste {row.extension} existe déjà")
        if row.extension in seen:
            errors.append(f"Poste en double (ligne {seen[row.extension]})")
        seen.setdefault(row.extension, index)
        report.append(
            {
                "line": index,
                "firstname": row.firstname,
                "lastname": row.lastname,
                "extension": row.extension,
                "email": row.email,
                "type": row.line,
                "voicemail": row.voicemail,
                "agent": row.agent,
                "errors": errors,
            }
        )
    return report


async def run_import(
    organization_id: int, content: str, **client_kwargs
) -> dict[str, Any]:
    """Create every valid row; one failure never stops the others."""
    report = await preview_import(organization_id, content, **client_kwargs)
    rows = parse_csv(content)
    created, failed = [], []
    for entry, spec in zip(report, rows):
        if entry["errors"]:
            failed.append({**entry})
            continue
        try:
            result = await create_extension(organization_id, spec, **client_kwargs)
            created.append(result)
        except (PbxError, PbxRouteError) as error:
            failed.append({**entry, "errors": [str(error)]})
    return {"created": created, "failed": failed}


def credentials_csv(created: list[dict]) -> str:
    """The one-time credentials sheet handed to the company's admin."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(
        [
            "nom",
            "poste",
            "identifiant",
            "mot_de_passe",
            "sip_utilisateur",
            "sip_mot_de_passe",
            "code_messagerie",
        ]
    )
    for item in created:
        c = item["credentials"]
        writer.writerow(
            [
                item["name"],
                item["extension"],
                c["login"],
                c["login_password"],
                c["sip_username"],
                c["sip_password"],
                c["voicemail_pin"] or "",
            ]
        )
    return out.getvalue()


# ------------------------------------------------------- queues & agents


async def _ai_destination(
    organization_id: int,
    connection,
    key: str,
    workflow_id: int,
    metadata_key: str,
    meta: dict,
) -> dict:
    """A PBX destination that hands the call to an AI agent (via ARI)."""
    from api.db import db_client

    if not connection.ari_configuration_id:
        raise PbxRouteError(
            "Reliez d'abord une configuration ARI (l'accès des agents IA au PBX).", 409
        )
    ari = await db_client.get_telephony_configuration_for_org(
        connection.ari_configuration_id, organization_id
    )
    if ari is None or ari.provider != "ari":
        raise PbxRouteError("Configuration ARI introuvable", 404)
    workflow = await db_client.get_workflow(
        workflow_id, organization_id=organization_id
    )
    if workflow is None:
        raise PbxRouteError("Agent introuvable", 404)
    stasis_app = (ari.credentials or {}).get("stasis_app_name") or (
        ari.credentials or {}
    ).get("app_name")
    rows = await db_client.list_phone_numbers_for_config(ari.id)
    row = next((r for r in rows if r.address_normalized == key), None)
    metadata = {metadata_key: meta}
    if row is None:
        await db_client.create_phone_number(
            organization_id=organization_id,
            telephony_configuration_id=ari.id,
            address=key,
            label=meta.get("label") or key,
            inbound_workflow_id=workflow.id,
            extra_metadata=metadata,
        )
    else:
        await db_client.update_phone_number(
            row.id,
            ari.id,
            inbound_workflow_id=workflow.id,
            is_active=True,
            extra_metadata={**(row.extra_metadata or {}), **metadata},
        )
    return {"type": "custom", "command": f"Stasis({stasis_app},inbound,called={key})"}


async def _clear_ai_destination(connection, key: str) -> None:
    from api.db import db_client

    if not connection.ari_configuration_id:
        return
    rows = await db_client.list_phone_numbers_for_config(
        connection.ari_configuration_id
    )
    for row in rows:
        if row.address_normalized == key:
            await db_client.delete_phone_number(row.id, connection.ari_configuration_id)


@dataclass
class NewQueue:
    label: str
    extension: str
    strategy: str = "leastrecent"
    ring_seconds: int = 20
    agent_ids: list[int] = field(default_factory=list)
    overflow_workflow_id: int | None = None
    overflow_after_seconds: int = 60


async def create_queue(organization_id: int, spec: NewQueue, **client_kwargs) -> dict:
    if not spec.label.strip():
        raise PbxRouteError("Nom de la file manquant", 422)
    if not EXTEN.match(spec.extension.strip()):
        raise PbxRouteError("Numéro de file invalide (2 à 10 chiffres)", 422)
    if spec.strategy not in STRATEGIES:
        raise PbxRouteError("Stratégie inconnue", 422)
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        context = await _internal_context(client)
        if await client.extensions(exten=spec.extension, context=context):
            raise PbxRouteError(f"Le numéro {spec.extension} est déjà utilisé", 409)
        name = f"{_slug(spec.label)}{secrets.token_hex(2)}"
        queue = await client.create_queue(
            {
                "name": name,
                "label": spec.label.strip()[:128],
                "options": [
                    ["strategy", spec.strategy],
                    ["timeout", str(max(5, min(spec.ring_seconds, 120)))],
                ],
                "enabled": True,
            }
        )
        try:
            extension = await client.create_extension(spec.extension, context)
            await client.associate_queue_extension(queue["id"], extension["id"])
            for agent_id in spec.agent_ids:
                await client.set_queue_member(queue["id"], agent_id)
        except PbxError:
            await client.delete_queue(queue["id"])
            raise
    if spec.overflow_workflow_id:
        await set_queue_overflow(
            organization_id,
            queue["id"],
            spec.overflow_workflow_id,
            spec.overflow_after_seconds,
            **client_kwargs,
        )
    return {"id": queue["id"], "name": spec.label.strip(), "extension": spec.extension}


async def set_queue_overflow(
    organization_id: int,
    queue_id: int,
    workflow_id: int | None,
    after_seconds: int = 60,
    **client_kwargs,
) -> dict:
    """Waiting too long, nobody answering, nobody logged in → an AI agent.

    ``workflow_id=None`` removes the overflow.
    """
    connection = await _connection(organization_id)
    key = f"{AI_KEY_PREFIX}q{queue_id}"
    async with client_for(connection, **client_kwargs) as client:
        queue = await client.queue(queue_id)
        if workflow_id is None:
            await client.update_queue(
                queue_id,
                {
                    **_queue_editable(queue),
                    "wait_time_threshold": None,
                    "wait_time_destination": None,
                },
            )
            await client.set_queue_fallbacks(queue_id, {})
            await _clear_ai_destination(connection, key)
            return {"queue_id": queue_id, "overflow": None}
        destination = await _ai_destination(
            organization_id,
            connection,
            key,
            workflow_id,
            OVERFLOW_METADATA_KEY,
            {
                "queue_id": queue_id,
                "label": f"Débordement {queue.get('label') or queue_id}",
            },
        )
        await client.update_queue(
            queue_id,
            {
                **_queue_editable(queue),
                "wait_time_threshold": max(10, min(after_seconds, 3600)),
                "wait_time_destination": destination,
            },
        )
        await client.set_queue_fallbacks(
            queue_id,
            {
                "noanswer_destination": destination,
                "busy_destination": destination,
                "congestion_destination": destination,
                "fail_destination": destination,
            },
        )
    return {
        "queue_id": queue_id,
        "overflow": {"workflow_id": workflow_id, "after_seconds": after_seconds},
    }


def _queue_editable(queue: dict) -> dict:
    """PUT replaces the queue: resend what we do not change."""
    keep = {
        "label",
        "options",
        "enabled",
        "timeout",
        "music_on_hold",
        "caller_id_mode",
        "caller_id_name",
        "announce_hold_time_on_entry",
        "ignore_forward",
        "retry_on_timeout",
        "ring_on_hold",
        "preprocess_subroutine",
        "wait_ratio_threshold",
        "wait_ratio_destination",
        "mark_answered_elsewhere",
        "data_quality",
        "dtmf_hangup_callee_enabled",
        "dtmf_hangup_caller_enabled",
        "dtmf_transfer_callee_enabled",
        "dtmf_transfer_caller_enabled",
        "dtmf_record_callee_enabled",
        "dtmf_record_caller_enabled",
        "dtmf_record_toggle",
        "wait_time_threshold",
        "wait_time_destination",
    }
    return {k: v for k, v in queue.items() if k in keep}


async def delete_queue(organization_id: int, queue_id: int, **client_kwargs) -> None:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        await client.delete_queue(queue_id)
    await _clear_ai_destination(connection, f"{AI_KEY_PREFIX}q{queue_id}")


async def set_queue_member(
    organization_id: int, queue_id: int, agent_id: int, member: bool, **client_kwargs
) -> None:
    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        if member:
            await client.set_queue_member(queue_id, agent_id)
        else:
            await client.remove_queue_member(queue_id, agent_id)


# ------------------------------------------- opening hours (business card)


def schedule_from_profile(profile) -> dict:
    """The business profile's hours as a PBX schedule (open + closures)."""
    open_periods = []
    for day, ranges in (profile.opening_hours or {}).items():
        for r in ranges:
            open_periods.append(
                {
                    "hours_start": r.open,
                    "hours_end": "23:59" if r.close == "24:00" else r.close,
                    "week_days": [DAY_NUMBERS[day]],
                }
            )
    open_periods.sort(key=lambda p: (p["week_days"][0], p["hours_start"]))
    exceptional = [
        {
            "hours_start": "00:00",
            "hours_end": "23:59",
            "month_days": [c.date.day],
            "months": [c.date.month],
            "week_days": [1, 2, 3, 4, 5, 6, 7],
        }
        for c in profile.closures
    ]
    return {
        "timezone": profile.timezone,
        "open_periods": open_periods,
        "exceptional_periods": exceptional,
    }


async def sync_opening_hours(
    organization_id: int,
    incall_ids: list[int],
    closed: Literal["ai_agent", "voicemail", "hangup"],
    workflow_id: int | None = None,
    voicemail_id: int | None = None,
    **client_kwargs,
) -> dict:
    """Push 'Mon entreprise' hours to the PBX numbers; outside hours → AI.

    One schedule per organization (named nimbora-horaires), updated in place,
    so a change of hours in the card is a single re-sync.
    """
    from api.services.business.profile import get_business_profile

    profile = await get_business_profile(organization_id)
    if not profile.opening_hours:
        raise PbxRouteError(
            "Renseignez d'abord les horaires dans « Mon entreprise »", 409
        )
    connection = await _connection(organization_id)
    key = f"{AI_KEY_PREFIX}h{organization_id}"
    if closed == "ai_agent":
        if not workflow_id:
            raise PbxRouteError("Choisissez l'agent IA qui répond hors horaires", 422)
        destination = await _ai_destination(
            organization_id,
            connection,
            key,
            workflow_id,
            AFTER_HOURS_METADATA_KEY,
            {"label": "Hors horaires"},
        )
    elif closed == "voicemail":
        if not voicemail_id:
            raise PbxRouteError("Choisissez la messagerie hors horaires", 422)
        destination = {"type": "voicemail", "voicemail_id": voicemail_id}
    else:
        destination = {"type": "hangup", "cause": "normal"}

    body = {
        "name": f"{SCHEDULE_NAME_PREFIX}-{organization_id}",
        "enabled": True,
        "closed_destination": destination,
        **schedule_from_profile(profile),
    }
    # Closures send to the same place as "closed".
    for period in body["exceptional_periods"]:
        period["destination"] = destination
    async with client_for(connection, **client_kwargs) as client:
        existing = next(
            (s for s in await client.schedules() if s.get("name") == body["name"]), None
        )
        if existing:
            await client.update_schedule(existing["id"], body)
            schedule_id = existing["id"]
        else:
            schedule_id = (await client.create_schedule(body))["id"]
        for incall_id in incall_ids:
            incall = await client.incall(incall_id)
            for other in incall.get("schedules") or []:
                if other.get("id") != schedule_id:
                    await client.dissociate_incall_schedule(incall_id, other["id"])
            await client.associate_incall_schedule(incall_id, schedule_id)
    if closed != "ai_agent":
        await _clear_ai_destination(connection, key)
    return {
        "schedule_id": schedule_id,
        "incall_ids": incall_ids,
        "closed": closed,
        "open_periods": len(body["open_periods"]),
        "closures": len(body["exceptional_periods"]),
        "brand": brand().name,
    }

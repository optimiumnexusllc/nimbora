"""Voice menus ("pour le service commercial, tapez 1") designed in NIMBORA and
published on the enterprise PBX.

The visual editor edits a :class:`MenuSpec` stored in NIMBORA. Publishing
speaks every prompt with the organization's voice, uploads the audio as PBX
sounds, turns each choice into a PBX destination — including "talk to an AI
agent", which hands the call to the agent through ARI — and creates or replaces
the PBX's IVR. Numbers are then pointed at the menu like any other destination.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, field_validator, model_validator

from api.services.branding import brand
from api.services.pbx.client import PbxClient, PbxError
from api.services.pbx.service import PbxRouteError, _connection, client_for

SOUND_CATEGORY = "menus-vocaux"
MENU_KEY_PREFIX = "nimbora-m"
IVR_METADATA_KEY = "pbx_ivr"
DIGIT_WORDS = {"*": "étoile", "#": "dièse"}
DIGIT_KEYS = {"*": "star", "#": "hash"}

ActionType = Literal[
    "queue", "group", "user", "ai", "voicemail", "menu", "conference", "hangup"
]
ACTION_LABELS = {
    "queue": "File d'attente",
    "group": "Groupe d'appel",
    "user": "Poste",
    "ai": "Agent IA",
    "voicemail": "Messagerie",
    "menu": "Autre menu",
    "conference": "Salle de conférence",
    "hangup": "Raccrocher",
}


class MenuAction(BaseModel):
    """Where a choice (or the fallback) sends the caller."""

    type: ActionType = "hangup"
    target_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _target_required(self):
        if self.type != "hangup" and self.target_id is None:
            raise ValueError(
                f"Choisissez la destination « {ACTION_LABELS[self.type]} »"
            )
        if self.type == "hangup":
            self.target_id = None
        return self


class MenuChoice(MenuAction):
    digit: str = Field(pattern=r"^[0-9*#]$")
    label: str = Field(min_length=1, max_length=80)

    @field_validator("label")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Libellé du choix manquant")
        return value


class MenuSpec(BaseModel):
    greeting_text: str = Field(default="", max_length=600)
    menu_text: str = Field(default="", max_length=800)
    invalid_text: str = Field(default="Ce choix n'est pas valide.", max_length=300)
    choices: list[MenuChoice] = Field(min_length=1, max_length=12)
    timeout_seconds: int = Field(default=5, ge=2, le=30)
    max_tries: int = Field(default=3, ge=1, le=5)
    fallback: MenuAction = Field(default_factory=MenuAction)
    voice_workflow_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _unique_digits(self):
        digits = [c.digit for c in self.choices]
        duplicates = sorted({d for d in digits if digits.count(d) > 1})
        if duplicates:
            raise ValueError(f"Touche utilisée deux fois : {', '.join(duplicates)}")
        return self

    def spoken_menu(self) -> str:
        """The menu text, written from the choices when left empty."""
        if self.menu_text.strip():
            return self.menu_text.strip()
        return " ".join(
            f"Pour {c.label[0].lower() + c.label[1:]}, tapez {DIGIT_WORDS.get(c.digit, c.digit)}."
            for c in self.choices
        )

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()


def menu_key(menu_id: int, slot: str) -> str:
    """Synthetic address of an AI hand-off (never collides with a number)."""
    return f"{MENU_KEY_PREFIX}{menu_id}-{DIGIT_KEYS.get(slot, slot)}"


def serialize(row) -> dict[str, Any]:
    spec = row.spec or {}
    published = bool(row.pbx_ivr_id and row.published_at)
    current = None
    try:
        current = MenuSpec.model_validate(spec).fingerprint()
    except ValueError:
        pass
    return {
        "id": row.id,
        "name": row.name,
        "spec": spec,
        "pbx_ivr_id": row.pbx_ivr_id,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "up_to_date": published and current == row.published_spec_hash,
        "last_error": row.last_error,
        "sounds": row.sounds or {},
    }


# ------------------------------------------------------------- drafts


async def create_menu(organization_id: int, name: str, spec: MenuSpec):
    from api.db import db_client

    name = name.strip()
    if not name:
        raise PbxRouteError("Nom du menu manquant", 422)
    await _check_references(organization_id, spec, menu_id=None)
    return await db_client.create_pbx_ivr_menu(
        organization_id, name[:128], spec.model_dump()
    )


async def update_menu(organization_id: int, menu_id: int, name: str, spec: MenuSpec):
    from api.db import db_client

    row = await db_client.get_pbx_ivr_menu(menu_id, organization_id)
    if row is None:
        raise PbxRouteError("Menu introuvable", 404)
    await _check_references(organization_id, spec, menu_id=menu_id)
    return await db_client.update_pbx_ivr_menu(
        menu_id,
        organization_id,
        {"name": (name.strip() or row.name)[:128], "spec": spec.model_dump()},
    )


async def _check_references(
    organization_id: int, spec: MenuSpec, *, menu_id: int | None
) -> None:
    """AI agents and sub-menus must belong to the organization."""
    from api.db import db_client

    actions: list[MenuAction] = [*spec.choices, spec.fallback]
    for action in actions:
        if action.type == "ai":
            workflow = await db_client.get_workflow(
                action.target_id, organization_id=organization_id
            )
            if workflow is None:
                raise PbxRouteError("Agent IA introuvable", 404)
        elif action.type == "menu":
            if action.target_id == menu_id:
                raise PbxRouteError("Un menu ne peut pas renvoyer vers lui-même", 422)
            if (
                await db_client.get_pbx_ivr_menu(action.target_id, organization_id)
                is None
            ):
                raise PbxRouteError("Sous-menu introuvable", 404)
    if spec.voice_workflow_id:
        workflow = await db_client.get_workflow(
            spec.voice_workflow_id, organization_id=organization_id
        )
        if workflow is None:
            raise PbxRouteError("Agent de la voix introuvable", 404)


# ------------------------------------------------------------ publish


async def _destination(
    organization_id: int,
    connection,
    menu_id: int,
    slot: str,
    action: MenuAction,
    label: str,
) -> dict:
    from api.db import db_client
    from api.services.pbx.admin import _ai_destination

    if action.type == "queue":
        return {"type": "queue", "queue_id": action.target_id}
    if action.type == "group":
        return {"type": "group", "group_id": action.target_id}
    if action.type == "conference":
        return {"type": "conference", "conference_id": action.target_id}
    if action.type == "user":
        return {"type": "user", "user_id": action.target_id}
    if action.type == "voicemail":
        return {"type": "voicemail", "voicemail_id": action.target_id}
    if action.type == "menu":
        target = await db_client.get_pbx_ivr_menu(action.target_id, organization_id)
        if target is None or not target.pbx_ivr_id:
            raise PbxRouteError(
                f"Publiez d'abord le sous-menu « {target.name if target else action.target_id} ».",
                409,
            )
        return {"type": "ivr", "ivr_id": target.pbx_ivr_id}
    if action.type == "ai":
        return await _ai_destination(
            organization_id,
            connection,
            menu_key(menu_id, slot),
            action.target_id,
            IVR_METADATA_KEY,
            {"menu_id": menu_id, "slot": slot, "label": label},
        )
    return {"type": "hangup", "cause": "normal"}


async def _ensure_category(client: PbxClient) -> None:
    categories = await client.sound_categories()
    if not any(c.get("name") == SOUND_CATEGORY for c in categories):
        await client.create_sound_category(SOUND_CATEGORY)


async def _upload(client: PbxClient, filename: str, audio: bytes) -> str:
    """Upload a prompt and return the path the PBX plays (no extension)."""
    from api.services.pbx.prompts import PBX_SOUND_FORMAT

    await client.upload_sound(
        SOUND_CATEGORY, filename, audio, sound_format=PBX_SOUND_FORMAT
    )
    category = await client.sound_category(SOUND_CATEGORY, file_name=filename)
    for item in category.get("files") or []:
        if item.get("name") == filename:
            for fmt in item.get("formats") or []:
                if fmt.get("path"):
                    return fmt["path"]
    raise PbxError(f"Le PBX n'a pas enregistré le message {filename}")


async def _stale_ai_keys(connection, menu_id: int, keep: set[str]) -> None:
    from api.db import db_client
    from api.services.pbx.admin import _clear_ai_destination

    if not connection.ari_configuration_id:
        return
    prefix = f"{MENU_KEY_PREFIX}{menu_id}-"
    rows = await db_client.list_phone_numbers_for_config(
        connection.ari_configuration_id
    )
    for row in rows:
        if (
            row.address_normalized.startswith(prefix)
            and row.address_normalized not in keep
        ):
            await _clear_ai_destination(connection, row.address_normalized)


async def publish_menu(organization_id: int, menu_id: int, **client_kwargs) -> dict:
    """Speak the prompts, upload them, and create or replace the PBX menu."""
    from api.db import db_client
    from api.services.pbx.prompts import synthesize_prompt

    row = await db_client.get_pbx_ivr_menu(menu_id, organization_id)
    if row is None:
        raise PbxRouteError("Menu introuvable", 404)
    try:
        spec = MenuSpec.model_validate(row.spec or {})
    except ValueError as error:
        raise PbxRouteError(f"Menu incomplet : {error}", 422) from error
    await _check_references(organization_id, spec, menu_id=menu_id)
    connection = await _connection(organization_id)

    texts = {"menu": spec.spoken_menu()}
    if spec.greeting_text.strip():
        texts["greeting"] = spec.greeting_text.strip()
    if spec.invalid_text.strip():
        texts["invalid"] = spec.invalid_text.strip()
    audio = {
        slot: await synthesize_prompt(
            organization_id, text, voice_workflow_id=spec.voice_workflow_id
        )
        for slot, text in texts.items()
    }

    try:
        async with client_for(connection, **client_kwargs) as client:
            await _ensure_category(client)
            sounds = {
                slot: await _upload(client, f"menu-{menu_id}-{slot}", data)
                for slot, data in audio.items()
            }
            choices = [
                {
                    "exten": choice.digit,
                    "destination": await _destination(
                        organization_id,
                        connection,
                        menu_id,
                        choice.digit,
                        choice,
                        choice.label,
                    ),
                }
                for choice in spec.choices
            ]
            fallback = await _destination(
                organization_id,
                connection,
                menu_id,
                "fallback",
                spec.fallback,
                f"{row.name} — sans choix",
            )
            body = {
                "name": row.name[:128],
                "description": f"{brand().name} — menu vocal n°{menu_id}",
                "greeting_sound": sounds.get("greeting"),
                "menu_sound": sounds["menu"],
                "invalid_sound": sounds.get("invalid"),
                "abort_sound": None,
                "timeout": spec.timeout_seconds,
                "max_tries": spec.max_tries,
                "invalid_destination": fallback,
                "timeout_destination": fallback,
                "abort_destination": fallback,
                "choices": choices,
            }
            ivr_id = row.pbx_ivr_id
            if ivr_id:
                try:
                    await client.update_ivr(ivr_id, body)
                except PbxError as error:
                    if error.status != 404:
                        raise
                    ivr_id = None  # deleted on the PBX side: create it again
            if not ivr_id:
                ivr_id = (await client.create_ivr(body))["id"]
            # Prompts that no longer exist (greeting removed…) are cleaned up.
            for slot in set(row.sounds or {}) - set(sounds):
                try:
                    await client.delete_sound(SOUND_CATEGORY, f"menu-{menu_id}-{slot}")
                except PbxError:
                    logger.opt(exception=True).warning("Stale menu prompt not removed")
    except (PbxError, PbxRouteError) as error:
        await db_client.update_pbx_ivr_menu(
            menu_id, organization_id, {"last_error": str(error)[:500]}
        )
        raise

    keep = {menu_key(menu_id, c.digit) for c in spec.choices if c.type == "ai"} | (
        {menu_key(menu_id, "fallback")} if spec.fallback.type == "ai" else set()
    )
    await _stale_ai_keys(connection, menu_id, keep)
    updated = await db_client.update_pbx_ivr_menu(
        menu_id,
        organization_id,
        {
            "pbx_ivr_id": ivr_id,
            "sounds": sounds,
            "published_at": datetime.now(UTC),
            "published_spec_hash": spec.fingerprint(),
            "last_error": None,
        },
    )
    return serialize(updated)


async def delete_menu(organization_id: int, menu_id: int, **client_kwargs) -> None:
    from api.db import db_client

    row = await db_client.get_pbx_ivr_menu(menu_id, organization_id)
    if row is None:
        raise PbxRouteError("Menu introuvable", 404)
    for other in await db_client.list_pbx_ivr_menus(organization_id):
        actions = [
            *(other.spec or {}).get("choices", []),
            (other.spec or {}).get("fallback") or {},
        ]
        if other.id != menu_id and any(
            a.get("type") == "menu" and a.get("target_id") == menu_id for a in actions
        ):
            raise PbxRouteError(
                f"Le menu « {other.name} » renvoie vers celui-ci : modifiez-le d'abord.",
                409,
            )
    if row.pbx_ivr_id or row.sounds:
        connection = await _connection(organization_id)
        async with client_for(connection, **client_kwargs) as client:
            if row.pbx_ivr_id:
                ivr = None
                try:
                    ivr = await client.ivr(row.pbx_ivr_id)
                except PbxError as error:
                    if error.status != 404:
                        raise
                if ivr and ivr.get("incalls"):
                    numbers = ", ".join(
                        e.get("exten")
                        for i in ivr["incalls"]
                        for e in i.get("extensions") or []
                        if e.get("exten")
                    )
                    raise PbxRouteError(
                        f"Des numéros arrivent sur ce menu ({numbers or 'numéros'}) : "
                        "changez leur destination d'abord.",
                        409,
                    )
                if ivr:
                    await client.delete_ivr(row.pbx_ivr_id)
            for slot in row.sounds or {}:
                try:
                    await client.delete_sound(SOUND_CATEGORY, f"menu-{menu_id}-{slot}")
                except PbxError as error:
                    if error.status != 404:
                        raise
        await _stale_ai_keys(connection, menu_id, set())
    await db_client.delete_pbx_ivr_menu(menu_id, organization_id)

"""Intelligent routing of an AI hand-off to the right human.

When a transfer tool uses ``destination_source = "smart"``, the destination is
chosen at hand-off time from the company's routing policy and the live state
of its enterprise PBX:

1. **VIP customer** (tag ``vip`` in customer memory) → the VIP destination.
2. **Usual advisor**: the employee who last served this customer (learned
   from the PBX call logs) when available right now → straight to them.
3. **Skill** asked by the AI agent (``skill`` argument: "facturation",
   "support technique"…) → the queue of that skill if someone in it is free,
   else a free agent having the skill (and the caller's language).
4. **Language** of the call → the queue of that language.
5. **Default** destination.

When nobody can answer, the policy decides: send to the default queue anyway
(the caller waits), or keep the customer with the AI agent and schedule a
human callback. Every decision carries its reason, shown in the simulator and
the logs.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

POLICY_KEY = "ROUTING_POLICY"
UNAVAILABLE_MODES = ("queue", "callback", "ai")
USUAL_ADVISOR_MIN_SECONDS = 30
_DEST_PREFIXES = ("pbx-queue:", "pbx-extension:", "queue:")

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "default_destination": "",
    "vip_destination": "",
    "usual_advisor": True,
    "usual_advisor_days": 180,
    "skills": [],  # [{"name": "facturation", "destination": "pbx-queue:3"}]
    "languages": {},  # {"en": "pbx-queue:5"}
    "agents": {},  # {"1001": {"skills": ["facturation"], "languages": ["fr", "en"]}}
    "when_unavailable": "queue",
    "callback_delay_minutes": 15,
}


class NoAgentAvailable(Exception):
    """Nobody can answer now and the policy keeps the customer with the AI."""

    def __init__(
        self,
        message: str,
        *,
        callback_scheduled: bool = False,
        steps: list[str] | None = None,
    ):
        super().__init__(message)
        self.callback_scheduled = callback_scheduled
        self.steps = steps or []


@dataclass
class RoutingDecision:
    destination: str
    reason: (
        str  # vip | usual_advisor | skill | skill_agent | language | default | fallback
    )
    explanation: str
    steps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "reason": self.reason,
            "explanation": self.explanation,
            "steps": self.steps,
        }


# ------------------------------------------------------------------ policy


def normalize(text: str | None) -> str:
    """Lower case, no accents, single spaces: "Support Technique " = "support technique"."""
    text = (
        unicodedata.normalize("NFKD", str(text or ""))
        .encode("ascii", "ignore")
        .decode()
    )
    return " ".join(text.lower().replace("-", " ").replace("_", " ").split())


def _valid_destination(value: Any) -> str:
    value = str(value or "").strip()
    if value and not value.startswith(_DEST_PREFIXES):
        raise ValueError(
            f"Destination « {value} » : file ou poste attendu (pbx-queue:, pbx-extension:, queue:)"
        )
    return value


def clean_policy(value: dict[str, Any] | None) -> dict[str, Any]:
    """Validated policy with defaults (raises ValueError on a bad value)."""
    raw = {**DEFAULTS, **(value or {})}
    policy: dict[str, Any] = {
        "enabled": bool(raw["enabled"]),
        "default_destination": _valid_destination(raw["default_destination"]),
        "vip_destination": _valid_destination(raw["vip_destination"]),
        "usual_advisor": bool(raw["usual_advisor"]),
        "usual_advisor_days": max(1, min(int(raw["usual_advisor_days"] or 180), 730)),
        "when_unavailable": raw["when_unavailable"]
        if raw["when_unavailable"] in UNAVAILABLE_MODES
        else "queue",
        "callback_delay_minutes": max(
            0, min(int(raw["callback_delay_minutes"] or 0), 1440)
        ),
    }
    skills, seen = [], set()
    for item in raw.get("skills") or []:
        name = str((item or {}).get("name") or "").strip()[:60]
        if not name or normalize(name) in seen:
            continue
        seen.add(normalize(name))
        skills.append(
            {"name": name, "destination": _valid_destination(item.get("destination"))}
        )
    policy["skills"] = skills[:40]
    policy["languages"] = {
        str(code).strip().lower()[:8]: _valid_destination(dest)
        for code, dest in (raw.get("languages") or {}).items()
        if str(code).strip() and str(dest or "").strip()
    }
    agents: dict[str, dict[str, list[str]]] = {}
    for extension, info in (raw.get("agents") or {}).items():
        extension = str(extension).strip()
        if not extension.isdigit():
            raise ValueError(f"Poste « {extension} » : numéro attendu")
        agents[extension] = {
            "skills": sorted(
                {
                    str(s).strip()
                    for s in (info or {}).get("skills") or []
                    if str(s).strip()
                }
            ),
            "languages": sorted(
                {
                    str(code).strip().lower()[:8]
                    for code in (info or {}).get("languages") or []
                    if str(code).strip()
                }
            ),
        }
    policy["agents"] = agents
    return policy


async def read_policy(organization_id: int) -> dict[str, Any]:
    from api.db import db_client

    value = await db_client.get_configuration_value(organization_id, POLICY_KEY, None)
    try:
        return clean_policy(value)
    except (ValueError, TypeError):
        logger.warning(
            f"Routing policy of org {organization_id} is invalid: defaults used"
        )
        return clean_policy(None)


async def save_policy(organization_id: int, value: dict[str, Any]) -> dict[str, Any]:
    from api.db import db_client

    policy = clean_policy(value)
    await db_client.upsert_configuration(organization_id, POLICY_KEY, policy)
    return policy


# ---------------------------------------------------------------- context


@dataclass
class LiveState:
    """Who can answer now, from the PBX's live supervision state."""

    available_extensions: set[str] = field(default_factory=set)
    queue_available: dict[str, int] = field(
        default_factory=dict
    )  # queue id → free agents
    known: bool = False  # False: no PBX state (assume destinations can answer)
    # Extensions of contact-center agents (their agent state decides) and
    # extensions on a call right now. An employee who is not an agent (a
    # branch advisor, say) is free whenever they are not on a call.
    agent_extensions: set[str] = field(default_factory=set)
    busy_extensions: set[str] = field(default_factory=set)

    def destination_free(self, destination: str) -> bool:
        if not self.known or not destination:
            return bool(destination)
        if destination.startswith("pbx-queue:"):
            return self.queue_available.get(destination.split(":", 1)[1], 0) > 0
        if destination.startswith("pbx-extension:"):
            extension = destination.split(":", 1)[1]
            if extension in self.agent_extensions:
                return extension in self.available_extensions
            return extension not in self.busy_extensions
        return True  # built-in contact-center queues: the caller waits there


async def live_state(organization_id: int) -> LiveState:
    from api.db import db_client

    if await db_client.get_pbx_connection(organization_id) is None:
        return LiveState()
    from api.services.pbx import supervision

    try:
        state = await supervision.live(organization_id)
    except Exception:  # noqa: BLE001 - route without live state rather than fail
        logger.opt(exception=True).warning("Routing: PBX live state unavailable")
        return LiveState()
    return LiveState(
        available_extensions={
            str(a.get("extension"))
            for a in state.get("agents") or []
            if a.get("state") == "available" and a.get("extension")
        },
        queue_available={
            str(q.get("id")): int(q.get("agents_available") or 0)
            for q in state.get("queues") or []
        },
        known=True,
        agent_extensions={
            str(a.get("extension"))
            for a in state.get("agents") or []
            if a.get("extension")
        },
        busy_extensions={
            str(c.get("extension"))
            for c in state.get("calls") or []
            if c.get("extension")
        },
    )


async def customer_profile(organization_id: int, phone: str | None):
    if not phone:
        return None
    from api.db import db_client
    from api.services.customer_memory.service import normalize_phone, phone_suffix

    normalized = normalize_phone(phone)
    if not normalized:
        return None
    return await db_client.find_customer_profile(
        organization_id, normalized, phone_suffix(normalized)
    )


def is_vip(profile) -> bool:
    if profile is None:
        return False
    tags = {normalize(t) for t in (profile.tags or [])}
    return "vip" in tags or bool((profile.attributes or {}).get("vip"))


def usual_advisor(profile, *, days: int, now: datetime) -> dict[str, Any] | None:
    if profile is None:
        return None
    advisor = (profile.attributes or {}).get("usual_advisor") or {}
    extension = str(advisor.get("extension") or "")
    if not extension.isdigit():
        return None
    try:
        at = datetime.fromisoformat(str(advisor.get("at")))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return advisor if now - at <= timedelta(days=days) else None


# ------------------------------------------------------------------ route


async def route(
    organization_id: int,
    *,
    caller_number: str | None,
    language: str | None,
    skill: str | None,
    policy: dict[str, Any] | None = None,
    state: LiveState | None = None,
    now: datetime | None = None,
) -> RoutingDecision:
    """The destination for this customer now (raises NoAgentAvailable)."""
    now = now or datetime.now(UTC)
    policy = policy or await read_policy(organization_id)
    state = state or await live_state(organization_id)
    profile = await customer_profile(organization_id, caller_number)
    language = normalize(language)[:8] or None
    wanted = normalize(skill)
    steps: list[str] = []

    def decide(destination: str, reason: str, explanation: str) -> RoutingDecision:
        steps.append(f"→ {explanation}")
        return RoutingDecision(destination, reason, explanation, steps)

    # 1. VIP
    if policy["vip_destination"] and is_vip(profile):
        if (
            state.destination_free(policy["vip_destination"])
            or policy["when_unavailable"] == "queue"
        ):
            return decide(
                policy["vip_destination"], "vip", "Client VIP : destination VIP"
            )
        steps.append("Client VIP, mais personne de libre à la destination VIP")
    elif policy["vip_destination"]:
        steps.append("Client non VIP")

    # 2. Usual advisor
    if policy["usual_advisor"]:
        advisor = usual_advisor(profile, days=policy["usual_advisor_days"], now=now)
        if advisor is None:
            steps.append("Pas de conseiller habituel connu")
        elif state.destination_free(f"pbx-extension:{advisor['extension']}"):
            name = advisor.get("name") or f"poste {advisor['extension']}"
            return decide(
                f"pbx-extension:{advisor['extension']}",
                "usual_advisor",
                f"Conseiller habituel disponible : {name}",
            )
        else:
            steps.append(
                f"Conseiller habituel ({advisor.get('name') or advisor['extension']}) indisponible"
            )

    # 3. Skill
    matched = None
    if wanted:
        matched = next(
            (
                s
                for s in policy["skills"]
                if normalize(s["name"]) == wanted
                or normalize(s["name"]) in wanted
                or wanted in normalize(s["name"])
            ),
            None,
        )
        if matched is None:
            steps.append(f"Compétence « {skill} » inconnue de la politique")
    if matched:
        if matched["destination"] and state.destination_free(matched["destination"]):
            return decide(
                matched["destination"], "skill", f"Compétence « {matched['name']} »"
            )
        experts = sorted(
            extension
            for extension, info in policy["agents"].items()
            if normalize(matched["name"]) in {normalize(s) for s in info["skills"]}
            and (not language or not info["languages"] or language in info["languages"])
            and state.destination_free(f"pbx-extension:{extension}")
        )
        if experts:
            return decide(
                f"pbx-extension:{experts[0]}",
                "skill_agent",
                f"Compétence « {matched['name']} » : poste {experts[0]} libre",
            )
        steps.append(f"Personne de libre pour « {matched['name']} »")

    # 4. Language
    if language and language in policy["languages"]:
        destination = policy["languages"][language]
        if state.destination_free(destination):
            return decide(destination, "language", f"Langue de l'appel : {language}")
        steps.append(f"Personne de libre pour la langue {language}")

    # 5. Default
    default = policy["default_destination"]
    if default and state.destination_free(default):
        return decide(default, "default", "Destination par défaut")

    # Nobody free.
    mode = policy["when_unavailable"]
    fallback = (
        (matched or {}).get("destination")
        or (policy["languages"].get(language or "") if language else "")
        or default
    )
    if mode == "queue" and fallback:
        return decide(
            fallback, "fallback", "Personne de libre : mise en attente dans la file"
        )
    if default:
        steps.append("Destination par défaut occupée")
    raise NoAgentAvailable(
        "Aucun conseiller n'est disponible pour le moment.", steps=steps
    )


async def resolve_for_transfer(
    organization_id: int,
    *,
    call_context_vars: dict[str, Any] | None,
    gathered_context_vars: dict[str, Any] | None,
    arguments: dict[str, Any] | None,
) -> RoutingDecision:
    """Smart routing of a transfer tool call; schedules a callback if asked."""
    initial = call_context_vars or {}
    gathered = gathered_context_vars or {}
    caller = initial.get("caller_number") or initial.get("phone_number")
    language = gathered.get("call_language") or initial.get("call_language")
    skill = (arguments or {}).get("skill") or (arguments or {}).get("motif")
    policy = await read_policy(organization_id)
    try:
        decision = await route(
            organization_id,
            caller_number=caller,
            language=language,
            skill=skill,
            policy=policy,
        )
    except NoAgentAvailable as error:
        if policy["when_unavailable"] == "callback" and caller:
            from api.services.contact_center.callbacks import create_or_update_callback

            await create_or_update_callback(
                organization_id,
                phone=str(caller),
                customer_name=gathered.get("customer_name"),
                reason=f"Aucun conseiller disponible ({skill or 'demande générale'})",
                source="ai_agent",
                assign_to="human",
                scheduled_at=datetime.now(UTC)
                + timedelta(minutes=policy["callback_delay_minutes"]),
            )
            raise NoAgentAvailable(
                "Aucun conseiller n'est disponible : un conseiller rappellera le client.",
                callback_scheduled=True,
            ) from error
        raise
    logger.info(
        f"[Routing org={organization_id}] {decision.reason} → {decision.destination}"
    )
    return decision


# -------------------------------------------------- usual advisor learning


async def remember_advisor(
    organization_id: int,
    profile_id: int,
    *,
    extension: str | None,
    name: str | None,
    seconds: int,
    at: datetime | None = None,
) -> bool:
    """A human answered this customer long enough: they become the usual advisor."""
    from api.db import db_client

    extension = str(extension or "")
    if (
        not extension.isdigit()
        or len(extension) > 6
        or seconds < USUAL_ADVISOR_MIN_SECONDS
    ):
        return False
    profile = await db_client.get_customer_profile(organization_id, profile_id)
    if profile is None:
        return False
    attributes = dict(profile.attributes or {})
    attributes["usual_advisor"] = {
        "extension": extension,
        "name": (name or "")[:128] or None,
        "at": (at or datetime.now(UTC)).isoformat(),
    }
    await db_client.update_customer_profile(
        organization_id, profile_id, {"attributes": attributes}
    )
    return True

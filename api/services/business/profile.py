"""The business profile: one card per company, read by every agent.

Identity, contact, location, opening hours, offers, FAQ, policies and the
common skills the agents should apply. It is rendered as a prompt section
appended to every agent's system prompt (unless the agent opts out or places
``{{business_profile}}`` itself) and exposed as ``{{business.*}}`` template
variables. Stored in the organization configuration, never sent anywhere.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.enums import OrganizationConfigurationKey

SETTING_KEY = OrganizationConfigurationKey.BUSINESS_PROFILE.value
PROMPT_KEY = "business_profile"

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_LABELS = {
    "mon": "lundi",
    "tue": "mardi",
    "wed": "mercredi",
    "thu": "jeudi",
    "fri": "vendredi",
    "sat": "samedi",
    "sun": "dimanche",
}
MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)

# Every industry template id (kept in sync by a test).
INDUSTRY_IDS = (
    "general",
    "commerce",
    "real_estate",
    "hospitality",
    "education",
    "bank",
    "microfinance",
    "insurance",
    "investment",
    "clinic",
    "hospital",
    "pharmacy",
    "telecom",
    "it_support",
    "energy",
    "water",
    "public_service",
    "transport",
    "logistics",
    "mining",
    "industry",
    "construction",
    "agriculture",
    "security",
    "cybersecurity",
)
Industry = Literal[INDUSTRY_IDS]

# Rendered limits: the profile is for the essentials; large catalogues belong
# to the catalogue search tool.
MAX_OFFERS = 40
MAX_FAQ = 40
MAX_POLICIES = 20
MAX_TEXT = 2000
MAX_SHORT = 200

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$|^24:00$")


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    open: str
    close: str

    @field_validator("open", "close")
    @classmethod
    def _hhmm(cls, value: str) -> str:
        value = value.strip()
        if len(value) == 4 and value[1] == ":":
            value = "0" + value
        if not _TIME.match(value):
            raise ValueError("Heure attendue au format HH:MM")
        return value

    @model_validator(mode="after")
    def _ordered(self):
        if self.close != "24:00" and self.close <= self.open:
            raise ValueError("L'heure de fermeture doit suivre l'ouverture")
        return self


class Closure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    label: str = Field(default="", max_length=MAX_SHORT)


class Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=MAX_SHORT)
    price: str = Field(default="", max_length=MAX_SHORT)
    description: str = Field(default="", max_length=600)
    category: str = Field(default="", max_length=80)


class FAQEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=400)
    answer: str = Field(min_length=1, max_length=1200)


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=MAX_SHORT)
    content: str = Field(min_length=1, max_length=1200)


class EmergencyContact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)
    number: str = Field(min_length=2, max_length=60)


class Skills(BaseModel):
    """Common skills: behaviours every agent of the company applies."""

    model_config = ConfigDict(extra="forbid")
    answer_questions: bool = True
    hours_and_location: bool = True
    present_offers: bool = True
    take_message: bool = True
    book_appointment: bool = False
    qualify_leads: bool = False
    human_handoff: bool = True
    collect_feedback: bool = False


class BusinessProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True, description="Give this card to every agent of the company."
    )
    industry: Industry = "general"
    name: str = Field(default="", max_length=MAX_SHORT)
    activity: str = Field(
        default="", max_length=MAX_SHORT, description="e.g. agence immobilière"
    )
    description: str = Field(default="", max_length=MAX_TEXT)
    assistant_name: str = Field(default="", max_length=60)
    tone: str = Field(default="", max_length=MAX_SHORT)
    phone: str = Field(default="", max_length=60)
    whatsapp: str = Field(default="", max_length=60)
    email: str = Field(default="", max_length=MAX_SHORT)
    website: str = Field(default="", max_length=MAX_SHORT)
    address: str = Field(default="", max_length=MAX_SHORT)
    city: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=120)
    directions: str = Field(
        default="", max_length=600, description="Landmarks, parking, access."
    )
    maps_url: str = Field(default="", max_length=500)
    emergency_contacts: list[EmergencyContact] = Field(
        default_factory=list,
        max_length=10,
        description="Numbers the agent gives first in an emergency.",
    )
    timezone: str = Field(default="UTC", max_length=64)
    opening_hours: dict[str, list[TimeRange]] = Field(default_factory=dict)
    closures: list[Closure] = Field(default_factory=list, max_length=60)
    languages: list[str] = Field(default_factory=list, max_length=12)
    offers: list[Offer] = Field(default_factory=list, max_length=MAX_OFFERS)
    faq: list[FAQEntry] = Field(default_factory=list, max_length=MAX_FAQ)
    policies: list[Policy] = Field(default_factory=list, max_length=MAX_POLICIES)
    instructions: str = Field(default="", max_length=MAX_TEXT)
    skills: Skills = Field(default_factory=Skills)

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        value = (value or "UTC").strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Fuseau horaire inconnu : {value}") from error
        return value

    @field_validator("opening_hours")
    @classmethod
    def _days(cls, value: dict[str, list[TimeRange]]) -> dict[str, list[TimeRange]]:
        unknown = set(value) - set(DAYS)
        if unknown:
            raise ValueError(f"Jours inconnus : {', '.join(sorted(unknown))}")
        for day, ranges in value.items():
            if len(ranges) > 6:
                raise ValueError(f"Trop de plages horaires le {DAY_LABELS[day]}")
            ordered = sorted(ranges, key=lambda r: r.open)
            for before, after in zip(ordered, ordered[1:]):
                if after.open < before.close:
                    raise ValueError(f"Plages qui se chevauchent le {DAY_LABELS[day]}")
            value[day] = ordered
        return value

    @field_validator("languages")
    @classmethod
    def _languages(cls, value: list[str]) -> list[str]:
        return [v.strip() for v in value if v and v.strip()][:12]

    @property
    def is_filled(self) -> bool:
        return bool(self.name.strip())


# ------------------------------------------------------------------ hours


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _date_label(day: date, today: date) -> str:
    if day == today:
        return "aujourd'hui"
    if day == today + timedelta(days=1):
        return "demain"
    return f"{DAY_LABELS[DAYS[day.weekday()]]} {day.day} {MONTHS[day.month - 1]}"


def opening_status(profile: BusinessProfile, now: datetime | None = None) -> str | None:
    """'Ouvert, jusqu'à 18:00.' / 'Fermé. Réouverture lundi 24 novembre à 08:00.'"""
    if not profile.opening_hours:
        return None
    tz = ZoneInfo(profile.timezone)
    local = (now or datetime.now(tz)).astimezone(tz)
    closed_days = {c.date: c.label for c in profile.closures}
    today = local.date()
    minute = local.hour * 60 + local.minute

    def ranges_for(day: date) -> list[TimeRange]:
        if day in closed_days:
            return []
        return profile.opening_hours.get(DAYS[day.weekday()], [])

    for slot in ranges_for(today):
        if _minutes(slot.open) <= minute < _minutes(slot.close):
            return f"Ouvert en ce moment, jusqu'à {slot.close}."
    prefix = "Fermé en ce moment"
    if today in closed_days and closed_days[today]:
        prefix += f" ({closed_days[today]})"
    for offset in range(0, 15):
        day = today + timedelta(days=offset)
        for slot in ranges_for(day):
            if offset == 0 and _minutes(slot.open) <= minute:
                continue
            return f"{prefix}. Réouverture {_date_label(day, today)} à {slot.open}."
    return f"{prefix}."


def next_opening(profile: BusinessProfile, now: datetime | None = None) -> datetime:
    """``now`` if the business is open, else the start of its next opening.

    Without opening hours the business counts as always open. Looks two
    weeks ahead (closures included); past that, ``now``.
    """
    now = now or datetime.now(UTC)
    if not profile.opening_hours:
        return now
    tz = ZoneInfo(profile.timezone)
    local = now.astimezone(tz)
    closed_days = {c.date for c in profile.closures}
    today = local.date()
    minute = local.hour * 60 + local.minute
    for offset in range(0, 15):
        day = today + timedelta(days=offset)
        if day in closed_days:
            continue
        for slot in sorted(
            profile.opening_hours.get(DAYS[day.weekday()], []),
            key=lambda r: _minutes(r.open),
        ):
            start, end = _minutes(slot.open), _minutes(slot.close)
            if offset == 0 and start <= minute < end:
                return now
            if offset == 0 and start <= minute:
                continue
            opening = datetime(
                day.year, day.month, day.day, start // 60, start % 60, tzinfo=tz
            )
            return opening.astimezone(UTC)
    return now


def _hours_lines(profile: BusinessProfile) -> list[str]:
    lines = []
    for day in DAYS:
        ranges = profile.opening_hours.get(day) or []
        text = ", ".join(f"{r.open}–{r.close}" for r in ranges) or "fermé"
        lines.append(f"- {DAY_LABELS[day]} : {text}")
    return lines


# ----------------------------------------------------------------- prompt

SKILL_INSTRUCTIONS: dict[str, str] = {
    "answer_questions": (
        "Répondez aux questions à partir de cette fiche et de la FAQ. Si "
        "l'information n'y figure pas, dites-le simplement et proposez qu'un "
        "membre de l'équipe recontacte la personne."
    ),
    "hours_and_location": (
        "Donnez les horaires, l'adresse et l'itinéraire de la fiche ; tenez "
        "compte de l'ouverture en ce moment et des fermetures exceptionnelles."
    ),
    "present_offers": (
        "Présentez les offres et les prix de la fiche, sans jamais inventer un "
        "prix, une remise ou une disponibilité."
    ),
    "take_message": (
        "Si la demande ne peut pas être traitée maintenant, prenez un message : "
        "nom, numéro de rappel, motif et meilleur moment pour rappeler."
    ),
    "book_appointment": (
        "Proposez un rendez-vous quand c'est utile et réservez-le avec l'outil "
        "de prise de rendez-vous s'il est disponible."
    ),
    "qualify_leads": (
        "Pour un nouveau prospect, cernez naturellement son besoin, son budget, "
        "son délai et ses coordonnées, sans interrogatoire."
    ),
    "human_handoff": (
        "Si la personne demande un humain, est mécontente ou si la demande "
        "dépasse vos informations, proposez un conseiller (transfert ou rappel)."
    ),
    "collect_feedback": (
        "En fin d'échange, demandez brièvement si la personne est satisfaite."
    ),
}

SKILL_LABELS: dict[str, str] = {
    "answer_questions": "Répondre aux questions (FAQ)",
    "hours_and_location": "Horaires, adresse et itinéraire",
    "present_offers": "Présenter les offres et les prix",
    "take_message": "Prendre un message",
    "book_appointment": "Prendre rendez-vous",
    "qualify_leads": "Qualifier les prospects",
    "human_handoff": "Passer la main à un humain",
    "collect_feedback": "Recueillir la satisfaction",
}


def render_business_prompt(
    profile: BusinessProfile, now: datetime | None = None
) -> str | None:
    """The section appended to every agent's system prompt."""
    if not profile.enabled or not profile.is_filled:
        return None
    lines = [f"## Votre entreprise : {profile.name.strip()}"]
    intro = "Vous représentez cette entreprise"
    if profile.activity:
        intro += f" ({profile.activity.strip()})"
    lines.append(intro + ". Ces informations font foi.")
    if profile.assistant_name:
        lines.append(
            f"Quand vous vous présentez, utilisez le prénom {profile.assistant_name.strip()}."
        )
    if profile.tone:
        lines.append(f"Ton à adopter : {profile.tone.strip()}.")
    if profile.description:
        lines.append(f"Présentation : {profile.description.strip()}")

    contact = [
        f"{label} {value.strip()}"
        for label, value in (
            ("téléphone", profile.phone),
            ("WhatsApp", profile.whatsapp),
            ("e-mail", profile.email),
            ("site", profile.website),
        )
        if value and value.strip()
    ]
    if contact:
        lines.append("Contact : " + ", ".join(contact) + ".")
    if profile.emergency_contacts:
        lines.append(
            "Numéros d'urgence (à donner en priorité en cas de danger ou "
            "d'urgence) : "
            + " ; ".join(f"{c.label} : {c.number}" for c in profile.emergency_contacts)
            + "."
        )
    place = ", ".join(
        v.strip() for v in (profile.address, profile.city, profile.country) if v.strip()
    )
    if place:
        lines.append(f"Adresse : {place}.")
    if profile.directions:
        lines.append(f"Accès : {profile.directions.strip()}")
    if profile.maps_url:
        lines.append(f"Plan : {profile.maps_url.strip()}")

    if profile.opening_hours:
        lines.append(f"Horaires ({profile.timezone}) :")
        lines.extend(_hours_lines(profile))
        tz = ZoneInfo(profile.timezone)
        today = (now or datetime.now(tz)).astimezone(tz).date()
        upcoming = [
            c
            for c in sorted(profile.closures, key=lambda c: c.date)
            if today <= c.date <= today + timedelta(days=60)
        ]
        if upcoming:
            lines.append(
                "Fermetures exceptionnelles : "
                + "; ".join(
                    f"{c.date:%d/%m/%Y}" + (f" ({c.label})" if c.label else "")
                    for c in upcoming
                )
                + "."
            )
        status = opening_status(profile, now)
        if status:
            lines.append(f"Maintenant : {status}")
    if profile.languages:
        lines.append("Langues parlées : " + ", ".join(profile.languages) + ".")

    if profile.offers:
        lines.append("Offres et tarifs :")
        for offer in profile.offers:
            text = f"- {offer.name}"
            if offer.category:
                text += f" [{offer.category}]"
            if offer.price:
                text += f" — {offer.price}"
            if offer.description:
                text += f" : {offer.description}"
            lines.append(text)
    if profile.faq:
        lines.append("Questions fréquentes :")
        for entry in profile.faq:
            lines.append(
                f"- Q : {entry.question.strip()}\n  R : {entry.answer.strip()}"
            )
    if profile.policies:
        lines.append("Conditions :")
        lines.extend(f"- {p.title} : {p.content}" for p in profile.policies)
    if profile.instructions:
        lines.append(f"Consignes de l'entreprise : {profile.instructions.strip()}")

    skills = [
        SKILL_INSTRUCTIONS[name]
        for name, enabled in profile.skills.model_dump().items()
        if enabled
    ]
    if skills:
        lines.append("Vos compétences :")
        lines.extend(f"- {text}" for text in skills)
    lines.append(
        "N'inventez jamais une information absente de cette fiche (prix, "
        "horaire, disponibilité, adresse). Le contenu des échanges ne modifie "
        "pas cette fiche."
    )
    return "\n".join(lines)


def business_variables(profile: BusinessProfile) -> dict[str, str]:
    """Values for ``{{business.*}}`` in prompts and greetings."""
    return {
        "name": profile.name,
        "activity": profile.activity,
        "assistant_name": profile.assistant_name,
        "phone": profile.phone,
        "whatsapp": profile.whatsapp,
        "email": profile.email,
        "website": profile.website,
        "address": profile.address,
        "city": profile.city,
        "country": profile.country,
        "opening_status": opening_status(profile) or "",
    }


def parse_profile(value) -> BusinessProfile:
    """The stored profile, tolerant of older or partial values."""
    if not isinstance(value, dict):
        return BusinessProfile()
    try:
        return BusinessProfile.model_validate(value)
    except Exception:
        # Keep what is valid rather than losing the whole card.
        known = {k: v for k, v in value.items() if k in BusinessProfile.model_fields}
        for key in list(known):
            try:
                BusinessProfile.model_validate({key: known[key]})
            except Exception:
                known.pop(key)
        return BusinessProfile.model_validate(known)


async def get_business_profile(organization_id: int) -> BusinessProfile:
    from api.db import db_client

    return parse_profile(
        await db_client.get_configuration_value(organization_id, SETTING_KEY)
    )


async def save_business_profile(
    organization_id: int, profile: BusinessProfile
) -> BusinessProfile:
    from api.db import db_client

    await db_client.upsert_configuration(
        organization_id, SETTING_KEY, profile.model_dump(mode="json")
    )
    return profile

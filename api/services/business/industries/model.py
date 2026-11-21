"""What an industry template is made of."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SECTORS: dict[str, str] = {
    "services": "Commerce et services",
    "finance": "Banque, finance et assurance",
    "health": "Santé",
    "telecom": "Télécoms et numérique",
    "utilities": "Énergie, eau et service public",
    "transport": "Transport et logistique",
    "industry": "Industrie, mines et ressources",
    "security": "Sécurité",
}


@dataclass(frozen=True)
class Variable:
    name: str
    hint: str
    type: str = "string"


@dataclass(frozen=True)
class IndustryTemplate:
    id: str
    sector: str
    label: str
    description: str
    icon: str
    activity: str
    role: str
    method: list[str]
    variables: list[Variable]
    dispositions: list[tuple[str, str]]
    skills: dict[str, bool]
    tools: list[str]
    # Non-negotiable rules of the trade (security, safety, compliance). They
    # come before the method in the agent's prompt and win over everything.
    rules: list[str] = field(default_factory=list)
    # Set-up advice shown to the company (not to the agent).
    recommendations: list[str] = field(default_factory=list)
    example_offers: list[dict[str, str]] = field(default_factory=list)
    example_faq: list[dict[str, str]] = field(default_factory=list)
    example_policies: list[dict[str, str]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sector": self.sector,
            "sector_label": SECTORS[self.sector],
            "label": self.label,
            "description": self.description,
            "icon": self.icon,
            "activity": self.activity,
            "method": self.method,
            "rules": self.rules,
            "recommendations": self.recommendations,
            "collects": [v.hint.split(" (")[0] for v in self.variables],
            "dispositions": [code for code, _ in self.dispositions],
            "skills": [k for k, v in self.skills.items() if v],
            "tools": self.tools,
            "example_offers": self.example_offers,
            "example_faq": self.example_faq,
            "example_policies": self.example_policies,
        }


COMMON_DISPOSITIONS = [
    ("information", "La personne voulait une information et l'a obtenue."),
    ("message_pris", "Un message a été pris pour être rappelé par l'équipe."),
    ("transfere", "La conversation a été passée à un conseiller humain."),
    ("hors_sujet", "Appel ou message sans rapport avec l'entreprise, erreur, spam."),
]

# Rules shared by every trade that handles accounts, money or identities.
NO_SECRETS = (
    "Ne demandez, ne notez et ne répétez JAMAIS un code PIN, un mot de passe, "
    "un code de validation reçu par SMS (OTP), un code secret Mobile Money, le "
    "numéro complet d'une carte ou son cryptogramme. Si la personne commence à "
    "en donner un, interrompez-la poliment et expliquez qu'on ne le demande "
    "jamais."
)
FRAUD_WARNING = (
    "Rappelez, si le sujet se présente, que l'entreprise ne demande jamais ces "
    "codes par téléphone, SMS ou WhatsApp : toute demande de ce type est une "
    "tentative de fraude."
)
NO_ACCOUNT_DATA = (
    "Ne communiquez aucune information sur un compte, un contrat ou un dossier "
    "(solde, opérations, montant dû, adresse) tant que l'identité n'a pas été "
    "vérifiée par un outil de l'entreprise ; sinon, orientez vers un conseiller "
    "ou l'application officielle."
)
NO_PROMISES = (
    "Ne promettez jamais un accord, un délai, un remboursement, un geste "
    "commercial ou une indemnisation : seule l'équipe décide. Dites ce qui va "
    "se passer ensuite."
)

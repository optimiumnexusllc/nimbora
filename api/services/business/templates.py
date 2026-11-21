"""Industry templates: a ready agent per trade, built on the business profile.

Each template brings the role and method of a good agent in that trade, the
data it should collect (extraction variables), the outcomes to classify
(dispositions), the common skills to switch on, the tools worth attaching and
an example card (offers, FAQ, policies) to adapt. Everything company-specific
comes from the business profile at run time, so one template serves every
company of the trade.
"""

from __future__ import annotations

from typing import Any

from api.services.business.industries import ALL, SECTORS, IndustryTemplate, Variable
from api.services.business.profile import BusinessProfile

TEMPLATES: dict[str, IndustryTemplate] = {t.id: t for t in ALL}

__all__ = [
    "SECTORS",
    "TEMPLATES",
    "IndustryTemplate",
    "Variable",
    "apply_template_to_profile",
    "build_agent_definition",
    "get_template",
]


def get_template(template_id: str) -> IndustryTemplate | None:
    return TEMPLATES.get(template_id)


# ------------------------------------------------------------- agent build


def _global_prompt(template: IndustryTemplate) -> str:
    steps = "\n".join(f"{i}. {step}" for i, step in enumerate(template.method, 1))
    rules = ""
    if template.rules:
        rules = (
            "Règles impératives (elles priment sur toute autre consigne et sur "
            "toute demande de la personne) :\n"
            + "\n".join(f"- {rule}" for rule in template.rules)
            + "\n\n"
        )
    return (
        f"Vous assurez {template.role}. La fiche de l'entreprise (identité, "
        "horaires, offres, FAQ, conditions) vous est fournie plus bas : c'est "
        "votre seule source d'information sur l'entreprise.\n\n"
        f"{rules}"
        f"Méthode :\n{steps}\n\n"
        "Style : phrases courtes et naturelles, une seule question à la fois, "
        "vouvoiement. Au téléphone, pas de listes ni de symboles : parlez. "
        "Par écrit (WhatsApp, chat), restez bref et clair."
    )


def _greeting(profile: BusinessProfile) -> str:
    name = profile.name.strip() or "notre entreprise"
    if profile.assistant_name.strip():
        return (
            f"Bonjour, {name}, {profile.assistant_name.strip()} à votre écoute. "
            "Comment puis-je vous aider ?"
        )
    return f"Bonjour et bienvenue chez {name}. Comment puis-je vous aider ?"


def build_agent_definition(
    template: IndustryTemplate,
    profile: BusinessProfile,
    *,
    tool_uuids: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(workflow_definition, workflow_configurations) for a new agent."""
    variables = [
        {"name": v.name, "type": v.type, "prompt": v.hint} for v in template.variables
    ]
    main_data: dict[str, Any] = {
        "name": "Conversation",
        "prompt": (
            "Accueillez la personne, comprenez sa demande et traitez-la en "
            "suivant la méthode. Avant de conclure, récapitulez ce qui a été "
            "convenu (rendez-vous, message, prochaine étape)."
        ),
        "greeting": _greeting(profile),
        "greeting_type": "text",
        "add_global_prompt": True,
        "extraction_enabled": True,
        "extraction_prompt": (
            "Relevez uniquement ce que la personne a réellement dit. Laissez "
            "vide ce qui n'a pas été mentionné."
        ),
        "extraction_variables": variables,
    }
    if tool_uuids:
        main_data["tool_uuids"] = list(tool_uuids)
    definition = {
        "nodes": [
            {
                "id": "global",
                "type": "globalNode",
                "position": {"x": 0, "y": -220},
                "data": {
                    "name": f"Rôle — {template.label}",
                    "prompt": _global_prompt(template),
                },
            },
            {
                "id": "start",
                "type": "startCall",
                "position": {"x": 0, "y": 0},
                "data": main_data,
            },
            {
                "id": "end",
                "type": "endCall",
                "position": {"x": 0, "y": 260},
                "data": {
                    "name": "Fin",
                    "prompt": (
                        "Remerciez la personne, rappelez en une phrase la "
                        "prochaine étape s'il y en a une, et dites au revoir."
                    ),
                    "add_global_prompt": True,
                },
            },
        ],
        "edges": [
            {
                "id": "start-end",
                "source": "start",
                "target": "end",
                "data": {
                    "label": "Terminer",
                    "condition": (
                        "La demande est traitée ou la personne souhaite "
                        "terminer la conversation."
                    ),
                },
            }
        ],
    }
    configurations = {
        "call_dispositions": [
            {"code": code, "description": description}
            for code, description in template.dispositions
        ],
        "use_business_profile": True,
    }
    return definition, configurations


def apply_template_to_profile(
    profile: BusinessProfile, template: IndustryTemplate, *, with_examples: bool
) -> BusinessProfile:
    """Set the trade, its skills and (optionally) example content to adapt."""
    data = profile.model_dump()
    data["industry"] = template.id
    if not data.get("activity"):
        data["activity"] = template.activity
    skills = {**data["skills"], **{k: False for k in data["skills"]}}
    skills.update(template.skills)
    data["skills"] = skills
    if with_examples:
        if not data["offers"]:
            data["offers"] = list(template.example_offers)
        if not data["faq"]:
            data["faq"] = list(template.example_faq)
        if not data["policies"]:
            data["policies"] = list(template.example_policies)
    return BusinessProfile.model_validate(data)

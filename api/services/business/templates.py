"""Industry templates: a ready agent per trade, built on the business profile.

Each template brings the role and method of a good agent in that trade, the
data it should collect (extraction variables), the outcomes to classify
(dispositions), the common skills to switch on, the tools worth attaching and
an example card (offers, FAQ, policies) to adapt. Everything company-specific
comes from the business profile at run time, so one template serves every
company of the trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from api.services.business.profile import BusinessProfile


@dataclass(frozen=True)
class Variable:
    name: str
    hint: str
    type: str = "string"


@dataclass(frozen=True)
class IndustryTemplate:
    id: str
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
    example_offers: list[dict[str, str]] = field(default_factory=list)
    example_faq: list[dict[str, str]] = field(default_factory=list)
    example_policies: list[dict[str, str]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "icon": self.icon,
            "activity": self.activity,
            "method": self.method,
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

TEMPLATES: dict[str, IndustryTemplate] = {
    t.id: t
    for t in [
        IndustryTemplate(
            id="general",
            label="Accueil général",
            description="Standard d'accueil polyvalent : informations, messages, orientation.",
            icon="building-2",
            activity="entreprise",
            role="l'accueil de l'entreprise, au téléphone, sur WhatsApp et sur le site",
            method=[
                "Comprendre en une question le motif de la demande.",
                "Répondre avec les informations de la fiche entreprise.",
                "Orienter vers la bonne personne ou prendre un message complet.",
            ],
            variables=[
                Variable("nom_client", "Nom de la personne (si donné)"),
                Variable("motif", "Motif de la demande, en une phrase"),
                Variable("telephone_rappel", "Numéro de rappel (si différent)"),
            ],
            dispositions=COMMON_DISPOSITIONS,
            skills={
                "answer_questions": True,
                "hours_and_location": True,
                "take_message": True,
                "human_handoff": True,
            },
            tools=["schedule_callback", "transfer_call"],
        ),
        IndustryTemplate(
            id="commerce",
            label="Commerce et boutique",
            description="Produits, prix, stock, commandes, livraison et service après-vente.",
            icon="shopping-bag",
            activity="boutique",
            role="le conseil client de la boutique : produits, commandes, livraisons et retours",
            method=[
                "Identifier le besoin (produit recherché, usage, budget) ou la commande concernée.",
                "Proposer les produits adaptés avec leur prix, sans inventer de stock.",
                "Pour une commande : prendre le numéro de commande et expliquer la suite.",
                "Pour une réclamation : recueillir les faits et ouvrir un ticket.",
            ],
            variables=[
                Variable("nom_client", "Nom du client"),
                Variable("produit", "Produit demandé ou concerné"),
                Variable("numero_commande", "Numéro de commande (si cité)"),
                Variable("quantite", "Quantité souhaitée", "number"),
                Variable("mode_livraison", "Livraison ou retrait souhaité, et lieu"),
                Variable("reclamation", "Problème signalé (si réclamation)"),
            ],
            dispositions=[
                ("commande_prise", "Le client a passé ou confirmé une commande."),
                ("suivi_commande", "Le client a demandé où en est sa commande."),
                (
                    "reclamation",
                    "Le client signale un problème avec un produit ou une livraison.",
                ),
                *COMMON_DISPOSITIONS,
            ],
            skills={
                "answer_questions": True,
                "hours_and_location": True,
                "present_offers": True,
                "take_message": True,
                "human_handoff": True,
                "collect_feedback": True,
            },
            tools=["send_message", "create_ticket", "schedule_callback"],
            example_offers=[
                {
                    "name": "Pagne wax 6 yards",
                    "price": "15 000 FCFA",
                    "description": "Coton imprimé, plusieurs motifs",
                    "category": "Textile",
                },
                {
                    "name": "Livraison Abidjan",
                    "price": "2 000 FCFA",
                    "description": "Sous 24 h ouvrées",
                    "category": "Service",
                },
            ],
            example_faq=[
                {
                    "question": "Livrez-vous à l'intérieur du pays ?",
                    "answer": "Oui, par transporteur, sous 2 à 4 jours ; le prix dépend de la ville.",
                },
                {
                    "question": "Puis-je payer par Mobile Money ?",
                    "answer": "Oui : Orange Money, MTN MoMo, Wave, ou en espèces à la livraison.",
                },
            ],
            example_policies=[
                {
                    "title": "Retours",
                    "content": "Échange sous 7 jours avec le ticket, article non porté.",
                },
            ],
        ),
        IndustryTemplate(
            id="real_estate",
            label="Immobilier",
            description="Location et vente : qualification du projet, biens disponibles, visites.",
            icon="home",
            activity="agence immobilière",
            role="le conseil de l'agence immobilière : qualification des projets, présentation des biens et organisation des visites",
            method=[
                "Cerner le projet : location ou achat, type de bien, quartier, nombre de pièces, budget, date d'emménagement.",
                "Présenter uniquement les biens de la fiche (ou du catalogue) qui correspondent, avec leur prix.",
                "Proposer une visite et la réserver ; sinon, prendre les coordonnées pour envoyer de nouvelles offres.",
                "Pour un propriétaire qui veut confier un bien : recueillir l'adresse, le type et le loyer ou prix visé.",
            ],
            variables=[
                Variable("nom_client", "Nom du prospect"),
                Variable("projet", "Location, achat, ou mise en gestion d'un bien"),
                Variable(
                    "type_bien", "Type de bien (studio, 2 pièces, villa, bureau…)"
                ),
                Variable("quartier", "Quartier ou ville souhaités"),
                Variable("nombre_pieces", "Nombre de pièces", "number"),
                Variable("budget", "Budget mensuel ou prix maximum, avec la devise"),
                Variable(
                    "date_emmenagement", "Date souhaitée d'emménagement ou d'achat"
                ),
                Variable("visite_souhaitee", "Bien et créneau de visite demandés"),
            ],
            dispositions=[
                ("visite_planifiee", "Une visite a été fixée."),
                (
                    "prospect_qualifie",
                    "Projet clair (type, quartier, budget) sans visite fixée.",
                ),
                ("mandat_proprietaire", "Un propriétaire veut confier un bien."),
                *COMMON_DISPOSITIONS,
            ],
            skills={
                "answer_questions": True,
                "hours_and_location": True,
                "present_offers": True,
                "take_message": True,
                "book_appointment": True,
                "qualify_leads": True,
                "human_handoff": True,
            },
            tools=["book_appointment", "send_message", "schedule_callback"],
            example_offers=[
                {
                    "name": "3 pièces Riviera 3",
                    "price": "240 000 FCFA / mois",
                    "description": "2 chambres, gardien, parking",
                    "category": "Location",
                },
                {
                    "name": "Villa duplex Angré",
                    "price": "95 000 000 FCFA",
                    "description": "4 chambres, jardin",
                    "category": "Vente",
                },
            ],
            example_faq=[
                {
                    "question": "Quels sont les frais d'agence ?",
                    "answer": "Un mois de loyer pour une location ; 5 % du prix pour une vente.",
                },
                {
                    "question": "Quels documents pour louer ?",
                    "answer": "Pièce d'identité, justificatif de revenus, 2 mois de caution et 1 mois d'avance.",
                },
            ],
            example_policies=[
                {
                    "title": "Visites",
                    "content": "Du lundi au samedi, sur rendez-vous, présence d'un agent obligatoire.",
                },
            ],
        ),
        IndustryTemplate(
            id="hospitality",
            label="Hôtellerie et restauration",
            description="Disponibilités, réservations, services, informations pratiques.",
            icon="bed-double",
            activity="hôtel",
            role="la réception : réservations, informations sur l'établissement et demandes des clients",
            method=[
                "Pour une réservation : dates d'arrivée et de départ, nombre de personnes, type de chambre ou de table.",
                "Donner les tarifs de la fiche et ce qui est inclus ; ne jamais garantir une disponibilité non confirmée.",
                "Réserver avec l'outil si disponible, sinon prendre la demande pour confirmation par l'équipe.",
                "Pour un client sur place : traiter la demande ou la transmettre au service concerné.",
            ],
            variables=[
                Variable("nom_client", "Nom de la réservation"),
                Variable("date_arrivee", "Date d'arrivée (ou date du repas)"),
                Variable("date_depart", "Date de départ"),
                Variable("nombre_personnes", "Nombre de personnes", "number"),
                Variable("type_chambre", "Type de chambre ou de table souhaité"),
                Variable(
                    "demandes_speciales",
                    "Demandes particulières (lit bébé, régime, navette…)",
                ),
            ],
            dispositions=[
                ("reservation", "Une réservation a été prise ou demandée."),
                ("modification", "Modification ou annulation d'une réservation."),
                (
                    "demande_client",
                    "Demande d'un client séjournant dans l'établissement.",
                ),
                *COMMON_DISPOSITIONS,
            ],
            skills={
                "answer_questions": True,
                "hours_and_location": True,
                "present_offers": True,
                "take_message": True,
                "book_appointment": True,
                "human_handoff": True,
                "collect_feedback": True,
            },
            tools=["book_appointment", "send_message", "transfer_call"],
            example_offers=[
                {
                    "name": "Chambre standard",
                    "price": "45 000 FCFA / nuit",
                    "description": "Petit-déjeuner inclus, Wi-Fi",
                    "category": "Chambres",
                },
                {
                    "name": "Suite junior",
                    "price": "85 000 FCFA / nuit",
                    "description": "Salon, vue lagune",
                    "category": "Chambres",
                },
            ],
            example_faq=[
                {
                    "question": "À quelle heure est le check-in ?",
                    "answer": "À partir de 14 h ; départ avant 12 h.",
                },
                {
                    "question": "Avez-vous une navette aéroport ?",
                    "answer": "Oui, 10 000 FCFA par trajet, à réserver 24 h avant.",
                },
            ],
            example_policies=[
                {
                    "title": "Annulation",
                    "content": "Gratuite jusqu'à 48 h avant l'arrivée ; ensuite, la première nuit est due.",
                },
            ],
        ),
        IndustryTemplate(
            id="insurance",
            label="Assurance",
            description="Devis, déclarations de sinistre, suivi de dossier, attestations.",
            icon="shield-check",
            activity="cabinet d'assurance",
            role="l'accueil du cabinet d'assurance : demandes de devis, déclarations de sinistre et suivi des dossiers",
            method=[
                "Identifier la demande : devis, sinistre, suivi de dossier, attestation ou résiliation.",
                "Pour un sinistre : date, lieu, circonstances, dégâts, personnes impliquées, numéro de contrat ; rassurer et expliquer les prochaines étapes.",
                "Pour un devis : type d'assurance, bien ou personne à assurer, garanties souhaitées.",
                "Ne jamais promettre une prise en charge ni un montant : seul un conseiller décide.",
            ],
            variables=[
                Variable("nom_client", "Nom de l'assuré ou du prospect"),
                Variable("numero_contrat", "Numéro de contrat (si client)"),
                Variable(
                    "type_demande", "Devis, sinistre, suivi, attestation, résiliation"
                ),
                Variable(
                    "type_assurance", "Auto, habitation, santé, voyage, prévoyance…"
                ),
                Variable("date_sinistre", "Date du sinistre"),
                Variable(
                    "description_sinistre",
                    "Circonstances et dégâts, en quelques phrases",
                ),
            ],
            dispositions=[
                ("sinistre_declare", "Un sinistre a été déclaré."),
                ("demande_devis", "Une demande de devis a été recueillie."),
                (
                    "suivi_dossier",
                    "Question sur un dossier ou un remboursement en cours.",
                ),
                *COMMON_DISPOSITIONS,
            ],
            skills={
                "answer_questions": True,
                "hours_and_location": True,
                "take_message": True,
                "book_appointment": True,
                "qualify_leads": True,
                "human_handoff": True,
            },
            tools=["create_ticket", "book_appointment", "schedule_callback"],
            example_offers=[
                {
                    "name": "Assurance auto tiers",
                    "price": "à partir de 60 000 FCFA / an",
                    "description": "Responsabilité civile, défense recours",
                    "category": "Auto",
                },
                {
                    "name": "Multirisque habitation",
                    "price": "à partir de 45 000 FCFA / an",
                    "description": "Incendie, dégâts des eaux, vol",
                    "category": "Habitation",
                },
            ],
            example_faq=[
                {
                    "question": "Combien de temps pour déclarer un sinistre ?",
                    "answer": "5 jours ouvrés ; 2 jours en cas de vol.",
                },
                {
                    "question": "Comment obtenir mon attestation ?",
                    "answer": "Par e-mail sous 24 h, sur simple demande avec votre numéro de contrat.",
                },
            ],
        ),
        IndustryTemplate(
            id="clinic",
            label="Clinique et cabinet médical",
            description="Rendez-vous, informations pratiques, orientation, urgences.",
            icon="stethoscope",
            activity="clinique",
            role="le secrétariat de la clinique : rendez-vous, informations pratiques et orientation des patients",
            method=[
                "Si la personne décrit une urgence vitale (douleur thoracique, difficulté à respirer, perte de connaissance, saignement abondant), lui dire d'appeler immédiatement les urgences et donner leur numéro s'il figure dans la fiche.",
                "Pour un rendez-vous : spécialité ou praticien, motif en quelques mots, première visite ou suivi, disponibilités.",
                "Ne jamais donner d'avis médical, de diagnostic ni de posologie : proposer un rendez-vous ou l'avis d'un soignant.",
                "Rester discret : ne demander que ce qui est utile au rendez-vous.",
            ],
            variables=[
                Variable("nom_patient", "Nom du patient"),
                Variable("specialite", "Spécialité ou praticien demandé"),
                Variable("motif_consultation", "Motif en quelques mots"),
                Variable("premiere_visite", "Première visite ou suivi"),
                Variable("creneau_souhaite", "Disponibilités ou créneau choisi"),
            ],
            dispositions=[
                ("rdv_pris", "Un rendez-vous a été pris."),
                ("rdv_modifie", "Rendez-vous déplacé ou annulé."),
                ("urgence_orientee", "La personne a été orientée vers les urgences."),
                *COMMON_DISPOSITIONS,
            ],
            skills={
                "answer_questions": True,
                "hours_and_location": True,
                "present_offers": True,
                "take_message": True,
                "book_appointment": True,
                "human_handoff": True,
            },
            tools=["book_appointment", "send_message", "transfer_call"],
            example_offers=[
                {
                    "name": "Consultation de médecine générale",
                    "price": "10 000 FCFA",
                    "category": "Consultations",
                },
                {
                    "name": "Consultation pédiatrique",
                    "price": "15 000 FCFA",
                    "category": "Consultations",
                },
            ],
            example_faq=[
                {
                    "question": "Acceptez-vous les assurances ?",
                    "answer": "Oui, la plupart des assurances santé ; apportez votre carte et une pièce d'identité.",
                },
                {
                    "question": "Faut-il être à jeun pour une prise de sang ?",
                    "answer": "Pour la glycémie et le bilan lipidique, oui : 8 à 12 heures. Le laboratoire confirme lors du rendez-vous.",
                },
            ],
            example_policies=[
                {
                    "title": "Urgences",
                    "content": "Service d'urgence ouvert 24 h/24 ; en cas d'urgence vitale, appelez le 185 (SAMU).",
                },
            ],
        ),
        IndustryTemplate(
            id="education",
            label="École et formation",
            description="Inscriptions, programmes, frais de scolarité, informations aux parents.",
            icon="graduation-cap",
            activity="établissement scolaire",
            role="le service des inscriptions et de l'accueil des familles",
            method=[
                "Identifier la personne : parent, élève, candidat ou entreprise.",
                "Pour une inscription : niveau ou formation visés, âge ou parcours, rentrée souhaitée ; expliquer les étapes et pièces à fournir.",
                "Donner les frais et calendriers de la fiche ; proposer une visite ou un entretien.",
                "Pour un élève inscrit : prendre le message pour l'enseignant ou l'administration.",
            ],
            variables=[
                Variable("nom_contact", "Nom du parent ou du candidat"),
                Variable("nom_eleve", "Nom de l'élève (si différent)"),
                Variable("niveau", "Classe, niveau ou formation visés"),
                Variable("rentree", "Rentrée ou session souhaitée"),
                Variable("question", "Question principale"),
            ],
            dispositions=[
                ("demande_inscription", "Demande d'inscription ou de dossier."),
                ("visite_entretien", "Une visite ou un entretien a été fixé."),
                ("vie_scolaire", "Message concernant un élève inscrit."),
                *COMMON_DISPOSITIONS,
            ],
            skills={
                "answer_questions": True,
                "hours_and_location": True,
                "present_offers": True,
                "take_message": True,
                "book_appointment": True,
                "qualify_leads": True,
                "human_handoff": True,
            },
            tools=["book_appointment", "send_message", "schedule_callback"],
            example_offers=[
                {
                    "name": "Cycle primaire (CP1 – CM2)",
                    "price": "450 000 FCFA / an",
                    "description": "Cantine en option",
                    "category": "Scolarité",
                },
                {
                    "name": "BTS Communication",
                    "price": "650 000 FCFA / an",
                    "description": "2 ans, stages inclus",
                    "category": "Supérieur",
                },
            ],
            example_faq=[
                {
                    "question": "Quand ont lieu les inscriptions ?",
                    "answer": "De mars à août, dans la limite des places ; tests d'entrée en mai.",
                },
                {
                    "question": "Peut-on payer en plusieurs fois ?",
                    "answer": "Oui, en 3 versements : à l'inscription, en janvier et en avril.",
                },
            ],
        ),
    ]
}


def get_template(template_id: str) -> IndustryTemplate | None:
    return TEMPLATES.get(template_id)


# ------------------------------------------------------------- agent build


def _global_prompt(template: IndustryTemplate) -> str:
    steps = "\n".join(f"{i}. {step}" for i, step in enumerate(template.method, 1))
    return (
        f"Vous assurez {template.role}. La fiche de l'entreprise (identité, "
        "horaires, offres, FAQ, conditions) vous est fournie plus bas : c'est "
        "votre seule source d'information sur l'entreprise.\n\n"
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

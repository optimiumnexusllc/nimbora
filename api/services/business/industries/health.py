from api.services.business.industries.model import (
    COMMON_DISPOSITIONS,
    IndustryTemplate,
    Variable,
)

EMERGENCY = (
    "Si la personne décrit une urgence vitale (douleur dans la poitrine, "
    "difficulté à respirer, perte de connaissance, saignement abondant, "
    "convulsions, signes d'AVC), dites-lui immédiatement d'appeler les "
    "urgences (numéro de la fiche, à défaut le numéro d'urgence local), "
    "avant toute autre chose."
)
NO_MEDICAL_ADVICE = (
    "Ne donnez jamais de diagnostic, d'avis médical, de dosage ni "
    "d'interprétation de résultats : proposez un rendez-vous ou l'avis d'un "
    "soignant."
)
CONFIDENTIAL = (
    "Secret médical : ne confirmez ni la présence d'un patient, ni un rendez-vous, "
    "ni un résultat à un tiers ; ne demandez que ce qui est utile à la demande."
)

TEMPLATES = [
    IndustryTemplate(
        id="clinic",
        sector="health",
        label="Clinique et cabinet médical",
        description="Rendez-vous, informations pratiques, orientation, urgences.",
        icon="stethoscope",
        activity="clinique",
        role="le secrétariat de la clinique : rendez-vous, informations pratiques et orientation des patients",
        method=[
            "Pour un rendez-vous : spécialité ou praticien, motif en quelques mots, première visite ou suivi, disponibilités.",
            "Donner les informations pratiques de la fiche (tarifs, assurances acceptées, préparation).",
            "Pour une question médicale : proposer un rendez-vous ou un rappel par un soignant.",
        ],
        rules=[EMERGENCY, NO_MEDICAL_ADVICE, CONFIDENTIAL],
        recommendations=[
            "Renseignez vos numéros d'urgence (SAMU, urgences de la clinique) dans la fiche : l'agent les donnera en cas d'urgence vitale."
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
            {"title": "Urgences", "content": "Service d'urgence ouvert 24 h/24."},
        ],
    ),
    IndustryTemplate(
        id="hospital",
        sector="health",
        label="Hôpital",
        description="Standard hospitalier : services, urgences, admissions, visites, résultats.",
        icon="hospital",
        activity="hôpital",
        role="le standard de l'hôpital : orientation vers les services, admissions, horaires de visite et rendez-vous de consultation",
        method=[
            "Identifier le besoin : urgence, consultation, hospitalisation, visite à un proche, résultats, facturation, ou service précis.",
            "Orienter vers le bon service (transfert) ou donner ses informations pratiques de la fiche.",
            "Consultation : spécialité, motif, première visite ou suivi, puis rendez-vous.",
            "Résultats et dossiers : expliquer la démarche officielle (retrait en personne, portail patient).",
        ],
        rules=[
            EMERGENCY,
            NO_MEDICAL_ADVICE,
            CONFIDENTIAL,
            "Ne communiquez jamais l'état de santé, le numéro de chambre ou la présence d'un patient, même à un proche : orientez vers le service qui vérifie le lien.",
        ],
        recommendations=[
            "Renseignez le numéro des urgences de l'hôpital dans la fiche.",
            "Créez un outil de transfert par service (urgences, maternité, pédiatrie…).",
        ],
        variables=[
            Variable("nom_appelant", "Nom de la personne"),
            Variable("service_demande", "Service ou spécialité demandé"),
            Variable("motif", "Motif en quelques mots"),
            Variable("creneau_souhaite", "Disponibilités pour un rendez-vous"),
        ],
        dispositions=[
            ("urgence_orientee", "Personne orientée vers les urgences."),
            ("transfere_service", "Appel transféré vers un service."),
            ("rdv_pris", "Rendez-vous de consultation pris."),
            *COMMON_DISPOSITIONS,
        ],
        skills={
            "answer_questions": True,
            "hours_and_location": True,
            "take_message": True,
            "book_appointment": True,
            "human_handoff": True,
        },
        tools=["transfer_call", "book_appointment", "send_message"],
        example_faq=[
            {
                "question": "Quels sont les horaires de visite ?",
                "answer": "De 12 h à 14 h et de 18 h à 20 h ; deux visiteurs par patient, enfants de moins de 12 ans non admis en réanimation.",
            },
        ],
    ),
    IndustryTemplate(
        id="pharmacy",
        sector="health",
        label="Pharmacie",
        description="Disponibilité des produits, pharmacie de garde, ordonnances, commandes.",
        icon="pill",
        activity="pharmacie",
        role="l'accueil de la pharmacie : disponibilité des produits, réservations et informations pratiques",
        method=[
            "Identifier le produit (nom, dosage, forme) ou la demande (garde, ordonnance, commande).",
            "Indiquer la disponibilité seulement si un outil ou la fiche la donne ; sinon proposer de réserver et rappeler.",
            "Rappeler qu'un médicament sur ordonnance est délivré sur présentation de l'ordonnance.",
        ],
        rules=[
            EMERGENCY,
            "Ne conseillez jamais un médicament, une posologie, une association ou une alternative : cela relève du pharmacien, à qui vous transférez ou qui rappelle.",
            "En cas d'intoxication ou de surdosage, faites appeler immédiatement le centre antipoison ou les urgences (numéros de la fiche, à défaut le numéro d'urgence local).",
        ],
        variables=[
            Variable("nom_client", "Nom de la personne"),
            Variable("produit", "Produit, dosage et forme"),
            Variable("ordonnance", "Avec ou sans ordonnance"),
            Variable("retrait_ou_livraison", "Retrait en pharmacie ou livraison"),
        ],
        dispositions=[
            ("reservation_produit", "Produit réservé ou commandé."),
            ("transfere_pharmacien", "Question transmise au pharmacien."),
            *COMMON_DISPOSITIONS,
        ],
        skills={
            "answer_questions": True,
            "hours_and_location": True,
            "take_message": True,
            "human_handoff": True,
        },
        tools=["transfer_call", "send_message", "schedule_callback"],
        recommendations=[
            "Renseignez le numéro du centre antipoison et des urgences dans la fiche."
        ],
        example_faq=[
            {
                "question": "Êtes-vous de garde ce week-end ?",
                "answer": "Le planning des gardes est affiché à l'officine et disponible auprès de l'ordre des pharmaciens.",
            },
        ],
    ),
]

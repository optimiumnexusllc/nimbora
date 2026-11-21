from api.services.business.industries.model import (
    COMMON_DISPOSITIONS,
    NO_PROMISES,
    IndustryTemplate,
    Variable,
)

TEMPLATES = [
    IndustryTemplate(
        id="general",
        sector="services",
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
        sector="services",
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
        rules=[NO_PROMISES],
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
        sector="services",
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
        rules=[
            "Ne demandez jamais de paiement, d'avance ni de frais de visite par téléphone ou message : les paiements se font à l'agence, contre reçu.",
            NO_PROMISES,
        ],
        variables=[
            Variable("nom_client", "Nom du prospect"),
            Variable("projet", "Location, achat, ou mise en gestion d'un bien"),
            Variable("type_bien", "Type de bien (studio, 2 pièces, villa, bureau…)"),
            Variable("quartier", "Quartier ou ville souhaités"),
            Variable("nombre_pieces", "Nombre de pièces", "number"),
            Variable("budget", "Budget mensuel ou prix maximum, avec la devise"),
            Variable("date_emmenagement", "Date souhaitée d'emménagement ou d'achat"),
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
        sector="services",
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
        rules=[
            "Ne communiquez jamais le numéro de chambre, la présence ou les coordonnées d'un client à un tiers.",
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
            ("demande_client", "Demande d'un client séjournant dans l'établissement."),
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
        id="education",
        sector="services",
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
        rules=[
            "Ne communiquez aucune information sur un élève (notes, présence, comportement, emploi du temps) : orientez vers l'administration qui vérifie l'identité du parent.",
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

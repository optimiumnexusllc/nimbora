from api.services.business.industries.model import (
    COMMON_DISPOSITIONS,
    NO_ACCOUNT_DATA,
    NO_PROMISES,
    IndustryTemplate,
    Variable,
)

TEMPLATES = [
    IndustryTemplate(
        id="transport",
        sector="transport",
        label="Transport de voyageurs",
        description="Car, train, avion, bateau, VTC : horaires, réservations, bagages, retards.",
        icon="bus",
        activity="compagnie de transport",
        role="le service client de la compagnie : horaires, réservations, bagages, retards et objets perdus",
        method=[
            "Identifier la demande : horaire, réservation, modification ou annulation, bagage, retard, objet perdu, réclamation.",
            "Réservation : trajet, date, heure souhaitée, nombre de passagers, classe ; tarifs de la fiche ; puis réservation ou lien de paiement officiel.",
            "Objet perdu ou bagage : trajet, date, description précise de l'objet, coordonnées ; enregistrer la déclaration.",
            "Retard ou annulation : donner l'information officielle disponible et les droits indiqués dans la fiche.",
        ],
        rules=[
            "Un accident, un malaise à bord ou une agression en cours : faites d'abord appeler les secours (numéros de la fiche, à défaut le numéro d'urgence local).",
            "N'annoncez un horaire, un retard ou une place disponible que s'ils viennent de la fiche ou d'un outil.",
            "Ne communiquez jamais la présence d'un passager ou ses coordonnées à un tiers.",
            NO_ACCOUNT_DATA,
            NO_PROMISES,
        ],
        recommendations=[
            "Publiez les perturbations du jour dans les consignes de la fiche."
        ],
        variables=[
            Variable("nom_passager", "Nom du passager"),
            Variable("trajet", "Départ et destination"),
            Variable("date_voyage", "Date et heure du voyage"),
            Variable("nombre_passagers", "Nombre de passagers", "number"),
            Variable("numero_reservation", "Numéro de réservation ou de billet"),
            Variable("objet_perdu", "Description de l'objet ou du bagage"),
        ],
        dispositions=[
            ("reservation", "Réservation effectuée ou demandée."),
            ("modification_annulation", "Modification ou annulation de billet."),
            ("bagage_objet_perdu", "Bagage ou objet perdu déclaré."),
            ("retard_reclamation", "Réclamation pour retard ou incident."),
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
        tools=["send_message", "create_ticket", "book_appointment"],
        example_offers=[
            {
                "name": "Abidjan – Yamoussoukro",
                "price": "6 000 FCFA",
                "description": "Départs 6 h, 9 h, 13 h, 17 h ; climatisé",
                "category": "Car",
            },
            {
                "name": "Abidjan – Bouaké",
                "price": "10 000 FCFA",
                "description": "Départs 7 h et 14 h",
                "category": "Car",
            },
        ],
        example_faq=[
            {
                "question": "Combien de bagages puis-je emporter ?",
                "answer": "Un bagage de 20 kg en soute et un bagage à main ; supplément de 2 000 FCFA par bagage supplémentaire.",
            },
        ],
    ),
    IndustryTemplate(
        id="logistics",
        sector="transport",
        label="Logistique, fret et livraison",
        description="Suivi de colis, enlèvements, devis fret, dédouanement, litiges.",
        icon="truck",
        activity="société de logistique",
        role="le service client logistique : suivi des envois, enlèvements, devis, dédouanement et litiges",
        method=[
            "Identifier la demande : suivi, enlèvement, devis, dédouanement, livraison manquée, colis endommagé ou perdu.",
            "Suivi : recueillir le numéro de suivi ; donner l'état seulement s'il vient d'un outil, sinon ouvrir une demande.",
            "Devis : origine, destination, nature de la marchandise, poids, volume, délai souhaité, incoterm si connu.",
            "Litige : numéro d'envoi, constat (photos), date de livraison, puis ouvrir un dossier.",
        ],
        rules=[
            "N'acceptez jamais de marchandises interdites ou dangereuses sans validation humaine (matières inflammables, produits chimiques, armes, produits soumis à licence) : orientez vers un conseiller.",
            "Ne communiquez aucune adresse de livraison ni information sur un envoi à quelqu'un qui n'en donne pas le numéro de suivi.",
            NO_PROMISES,
        ],
        variables=[
            Variable("nom_client", "Nom du client ou de l'entreprise"),
            Variable("numero_suivi", "Numéro de suivi ou de lettre de transport"),
            Variable("origine", "Lieu d'enlèvement"),
            Variable("destination", "Destination"),
            Variable("marchandise", "Nature de la marchandise"),
            Variable("poids_kg", "Poids en kilogrammes", "number"),
            Variable("probleme", "Problème signalé (retard, dommage, perte)"),
        ],
        dispositions=[
            ("suivi_envoi", "Question de suivi d'un envoi."),
            ("demande_devis", "Demande de devis qualifiée."),
            ("enlevement_planifie", "Enlèvement ou livraison planifié."),
            ("litige", "Retard, dommage ou perte déclaré."),
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
        tools=["create_ticket", "send_message", "book_appointment"],
        example_faq=[
            {
                "question": "Combien de temps pour un envoi Abidjan – Ouagadougou ?",
                "answer": "3 à 5 jours ouvrés par route, hors délais de dédouanement.",
            },
        ],
    ),
]

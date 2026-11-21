from api.services.business.industries.model import (
    COMMON_DISPOSITIONS,
    FRAUD_WARNING,
    NO_ACCOUNT_DATA,
    NO_PROMISES,
    NO_SECRETS,
    IndustryTemplate,
    Variable,
)

TEMPLATES = [
    IndustryTemplate(
        id="telecom",
        sector="telecom",
        label="Opérateur télécom et internet",
        description="Forfaits, factures, pannes réseau, installation fibre, SIM et portabilité.",
        icon="radio-tower",
        activity="opérateur de télécommunications",
        role="le service client de l'opérateur : offres, factures, pannes, installations et cartes SIM",
        method=[
            "Identifier la demande : offre ou forfait, facture, panne (mobile, internet, fibre), installation, carte SIM, portabilité, résiliation.",
            "Panne : localiser (quartier, ville), préciser le service touché, depuis quand, et si le problème concerne une seule personne ou tout le voisinage ; faire les vérifications simples (redémarrer la box, voyants) puis ouvrir un ticket.",
            "Offres : présenter les forfaits de la fiche et aider à choisir selon l'usage (appels, données, budget).",
            "Installation : adresse, type d'habitation, disponibilités, puis rendez-vous technicien.",
        ],
        rules=[
            "Ne faites jamais de changement de carte SIM, de déblocage (code PUK), de transfert de ligne ni de modification de titulaire : ces opérations se font en boutique ou après vérification d'identité par un conseiller.",
            NO_SECRETS,
            NO_ACCOUNT_DATA,
            FRAUD_WARNING,
            "N'annoncez une panne générale ou une date de rétablissement que si la fiche ou un outil l'indique.",
            NO_PROMISES,
        ],
        recommendations=[
            "Publiez les incidents réseau en cours dans les consignes de la fiche : tous les agents les annonceront.",
            "Créez un outil de tickets pour les pannes et un outil de rendez-vous technicien.",
        ],
        variables=[
            Variable("nom_client", "Nom du client"),
            Variable("numero_ligne", "Numéro de ligne ou de contrat concerné"),
            Variable(
                "type_demande",
                "Offre, facture, panne, installation, SIM, portabilité, résiliation",
            ),
            Variable("service_concerne", "Mobile, internet mobile, fibre, ADSL, TV"),
            Variable(
                "localisation", "Quartier et ville (pour une panne ou une installation)"
            ),
            Variable("depuis_quand", "Début du problème"),
            Variable("description_probleme", "Symptômes décrits"),
        ],
        dispositions=[
            ("panne_signalee", "Panne ou dysfonctionnement signalé, ticket ouvert."),
            ("souscription", "Intérêt pour une offre ou souscription."),
            ("installation_planifiee", "Rendez-vous d'installation fixé."),
            ("facture", "Question ou contestation de facture."),
            ("resiliation", "Demande de résiliation ou de portabilité."),
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
            "collect_feedback": True,
        },
        tools=["create_ticket", "book_appointment", "send_message"],
        example_offers=[
            {
                "name": "Forfait Smart 10 Go",
                "price": "5 000 FCFA / mois",
                "description": "10 Go, appels illimités vers le réseau",
                "category": "Mobile",
            },
            {
                "name": "Fibre 50 Mb/s",
                "price": "25 000 FCFA / mois",
                "description": "Installation offerte, box Wi-Fi 6",
                "category": "Internet",
            },
        ],
        example_faq=[
            {
                "question": "Comment garder mon numéro en changeant d'opérateur ?",
                "answer": "Demandez la portabilité en boutique avec votre pièce d'identité ; elle prend effet sous 48 h.",
            },
            {
                "question": "Ma box ne capte plus, que faire ?",
                "answer": "Débranchez-la 30 secondes puis rebranchez-la ; si le voyant reste rouge, un ticket est ouvert pour un technicien.",
            },
        ],
    ),
    IndustryTemplate(
        id="it_support",
        sector="telecom",
        label="Support informatique et SaaS",
        description="Helpdesk : incidents, accès, demandes, priorisation et suivi des tickets.",
        icon="monitor-cog",
        activity="société de services informatiques",
        role="le support informatique de premier niveau : qualification des incidents, demandes courantes et suivi des tickets",
        method=[
            "Identifier l'utilisateur, son entreprise et le service touché.",
            "Qualifier l'impact (une personne, une équipe, toute l'entreprise) et l'urgence pour fixer la priorité.",
            "Recueillir le message d'erreur exact, depuis quand, ce qui a changé, et les étapes pour reproduire.",
            "Proposer les vérifications simples de la FAQ, puis ouvrir un ticket complet et donner son numéro.",
        ],
        rules=[
            "Ne demandez jamais de mot de passe ni de code de double authentification, et ne réinitialisez aucun accès sans la procédure de vérification de l'entreprise.",
            "Ne guidez jamais une manipulation risquée (suppression de données, modification de serveur, désactivation d'antivirus) : escaladez à un technicien.",
            "Un soupçon de piratage (rançongiciel, compte compromis) passe en priorité critique : conseillez de débrancher l'appareil du réseau sans l'éteindre, puis escaladez immédiatement.",
        ],
        recommendations=[
            "Créez un outil de tickets relié à votre helpdesk (Zendesk, Freshdesk…) pour que les tickets arrivent directement chez les techniciens."
        ],
        variables=[
            Variable("nom_utilisateur", "Nom de l'utilisateur"),
            Variable("entreprise", "Entreprise cliente"),
            Variable("service_touche", "Application ou équipement concerné"),
            Variable("message_erreur", "Message d'erreur exact"),
            Variable("impact", "Une personne, une équipe ou toute l'entreprise"),
            Variable("priorite", "Critique, haute, normale ou basse"),
        ],
        dispositions=[
            (
                "incident_critique",
                "Incident bloquant pour plusieurs personnes ou suspicion de piratage.",
            ),
            ("incident", "Incident ouvert en ticket."),
            ("demande_service", "Demande courante (accès, installation, matériel)."),
            ("suivi_ticket", "Question sur un ticket existant."),
            *COMMON_DISPOSITIONS,
        ],
        skills={
            "answer_questions": True,
            "take_message": True,
            "human_handoff": True,
            "collect_feedback": True,
        },
        tools=["create_ticket", "transfer_call", "send_message"],
        example_faq=[
            {
                "question": "Je n'arrive plus à me connecter à ma messagerie.",
                "answer": "Vérifiez la connexion internet puis réessayez dans un navigateur privé ; si l'erreur persiste, un ticket est ouvert pour réinitialiser l'accès après vérification.",
            },
        ],
    ),
]

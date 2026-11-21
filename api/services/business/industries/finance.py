from api.services.business.industries.model import (
    COMMON_DISPOSITIONS,
    FRAUD_WARNING,
    NO_ACCOUNT_DATA,
    NO_PROMISES,
    NO_SECRETS,
    IndustryTemplate,
    Variable,
)

PCI = "Activez le mode PCI dans Confidentialité : les numéros de carte et codes dictés sont masqués partout (transcriptions, journaux, résumés)."
FRAUD_TEAM = (
    "Créez un outil de transfert vers l'équipe fraude / opposition, joignable 24 h/24."
)

TEMPLATES = [
    IndustryTemplate(
        id="bank",
        sector="finance",
        label="Banque",
        description="Comptes, cartes, crédits, agences, opposition et fraude.",
        icon="landmark",
        activity="banque",
        role="l'accueil de la banque : renseignements sur les produits, cartes, crédits, agences et prise de rendez-vous avec un conseiller",
        method=[
            "Identifier la demande : produit ou tarif, carte, crédit, ouverture de compte, réclamation, agence, ou urgence.",
            "Urgence (carte perdue ou volée, opération inconnue, fraude) : traiter en priorité, donner le numéro d'opposition de la fiche et transférer à l'équipe fraude.",
            "Produits et crédits : présenter les offres et conditions de la fiche, cerner le besoin (montant, durée, revenus approximatifs) et proposer un rendez-vous avec un conseiller.",
            "Ouverture de compte : expliquer les pièces à fournir et les étapes.",
            "Réclamation : recueillir les faits (date, montant, canal) et ouvrir un dossier.",
        ],
        rules=[
            NO_SECRETS,
            NO_ACCOUNT_DATA,
            "Ne donnez aucun conseil d'investissement personnalisé et ne garantissez aucun taux ni accord de crédit : les conditions définitives sont fixées par un conseiller après étude du dossier.",
            "Une personne qui signale une perte, un vol ou une opération qu'elle ne reconnaît pas passe avant tout le reste.",
            FRAUD_WARNING,
            NO_PROMISES,
        ],
        recommendations=[
            PCI,
            FRAUD_TEAM,
            "Renseignez le numéro d'opposition carte (24 h/24) dans les numéros d'urgence de la fiche.",
        ],
        variables=[
            Variable("nom_client", "Nom de la personne"),
            Variable("client_banque", "Déjà client ou non"),
            Variable(
                "type_demande", "Carte, crédit, compte, réclamation, agence, fraude…"
            ),
            Variable("produit", "Produit concerné (compte, carte, crédit immobilier…)"),
            Variable("montant_souhaite", "Montant du crédit envisagé", "number"),
            Variable("duree_souhaitee", "Durée envisagée"),
            Variable("agence", "Agence de la personne ou la plus proche"),
            Variable(
                "description_incident", "Faits signalés (opération, date, montant)"
            ),
        ],
        dispositions=[
            (
                "opposition_fraude",
                "Carte perdue ou volée, opération contestée ou fraude signalée.",
            ),
            ("demande_credit", "Projet de crédit qualifié ou rendez-vous conseiller."),
            ("ouverture_compte", "Demande d'ouverture de compte."),
            ("reclamation", "Réclamation enregistrée."),
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
        tools=["transfer_call", "book_appointment", "create_ticket"],
        example_offers=[
            {
                "name": "Compte courant particulier",
                "price": "2 500 FCFA / mois",
                "description": "Carte Visa Classic, application mobile",
                "category": "Comptes",
            },
            {
                "name": "Crédit immobilier",
                "price": "à partir de 7,5 % / an",
                "description": "Jusqu'à 20 ans, sous réserve d'acceptation",
                "category": "Crédits",
            },
        ],
        example_faq=[
            {
                "question": "Quelles pièces pour ouvrir un compte ?",
                "answer": "Pièce d'identité valide, justificatif de domicile de moins de 3 mois, et un justificatif de revenus.",
            },
            {
                "question": "Ma carte est bloquée après 3 codes faux, que faire ?",
                "answer": "Elle se débloque à l'agence ou au guichet automatique de la banque avec la carte et une pièce d'identité.",
            },
        ],
        example_policies=[
            {
                "title": "Sécurité",
                "content": "La banque ne demande jamais votre code, vos identifiants ni un code reçu par SMS.",
            },
        ],
    ),
    IndustryTemplate(
        id="microfinance",
        sector="finance",
        label="Microfinance et Mobile Money",
        description="Microcrédit, épargne, transactions Mobile Money, agents et litiges.",
        icon="smartphone",
        activity="institution de microfinance",
        role="le service client : épargne, microcrédit, transferts d'argent mobile et réseau d'agents",
        method=[
            "Identifier la demande : transaction échouée ou en attente, envoi au mauvais numéro, microcrédit, épargne, agent, compte bloqué.",
            "Transaction : recueillir l'identifiant de transaction, la date, le montant et le numéro destinataire, puis ouvrir un dossier de réclamation.",
            "Microcrédit : cerner l'activité, le montant, la durée et l'ancienneté ; présenter les conditions de la fiche ; proposer un rendez-vous en agence.",
            "Orienter vers l'agent ou l'agence la plus proche quand une démarche physique est nécessaire.",
        ],
        rules=[
            NO_SECRETS,
            NO_ACCOUNT_DATA,
            "N'annulez et ne promettez jamais l'annulation d'un transfert : seule l'équipe réclamations peut agir après vérification.",
            "Si la personne parle d'un changement de carte SIM qu'elle n'a pas demandé ou d'un appel lui réclamant un code, traitez-le comme une fraude : transfert immédiat.",
            FRAUD_WARNING,
        ],
        recommendations=[PCI, FRAUD_TEAM],
        variables=[
            Variable("nom_client", "Nom du client"),
            Variable("numero_compte_mobile", "Numéro Mobile Money concerné"),
            Variable("id_transaction", "Identifiant de la transaction"),
            Variable("montant", "Montant concerné", "number"),
            Variable("date_transaction", "Date et heure de la transaction"),
            Variable("numero_destinataire", "Numéro du destinataire"),
            Variable("activite", "Activité financée (pour un microcrédit)"),
        ],
        dispositions=[
            (
                "litige_transaction",
                "Transaction échouée, en attente ou envoyée au mauvais numéro.",
            ),
            ("fraude", "Fraude ou changement de SIM suspect signalé."),
            ("demande_credit", "Demande de microcrédit qualifiée."),
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
        tools=["create_ticket", "transfer_call", "send_message"],
        example_offers=[
            {
                "name": "Microcrédit commerce",
                "price": "taux de 1,5 % / mois",
                "description": "De 50 000 à 2 000 000 FCFA, 3 à 12 mois",
                "category": "Crédits",
            },
            {
                "name": "Épargne tontine",
                "price": "gratuit",
                "description": "Versements quotidiens via Mobile Money",
                "category": "Épargne",
            },
        ],
        example_faq=[
            {
                "question": "J'ai envoyé de l'argent au mauvais numéro.",
                "answer": "Donnez l'identifiant de la transaction : une réclamation est ouverte et traitée sous 72 h ouvrées.",
            },
        ],
    ),
    IndustryTemplate(
        id="insurance",
        sector="finance",
        label="Assurance",
        description="Devis, déclarations de sinistre, suivi de dossier, attestations.",
        icon="shield-check",
        activity="cabinet d'assurance",
        role="l'accueil du cabinet d'assurance : demandes de devis, déclarations de sinistre et suivi des dossiers",
        method=[
            "Identifier la demande : devis, sinistre, suivi de dossier, attestation ou résiliation.",
            "Pour un sinistre : date, lieu, circonstances, dégâts, personnes impliquées, numéro de contrat ; rassurer et expliquer les prochaines étapes.",
            "Pour un devis : type d'assurance, bien ou personne à assurer, garanties souhaitées.",
        ],
        rules=[
            "Ne promettez jamais une prise en charge, un montant d'indemnisation ni un délai : seul un gestionnaire décide après étude du dossier.",
            "En cas d'accident avec blessés en cours, faites d'abord appeler les secours (numéros d'urgence de la fiche).",
            NO_ACCOUNT_DATA,
        ],
        variables=[
            Variable("nom_client", "Nom de l'assuré ou du prospect"),
            Variable("numero_contrat", "Numéro de contrat (si client)"),
            Variable(
                "type_demande", "Devis, sinistre, suivi, attestation, résiliation"
            ),
            Variable("type_assurance", "Auto, habitation, santé, voyage, prévoyance…"),
            Variable("date_sinistre", "Date du sinistre"),
            Variable(
                "description_sinistre", "Circonstances et dégâts, en quelques phrases"
            ),
        ],
        dispositions=[
            ("sinistre_declare", "Un sinistre a été déclaré."),
            ("demande_devis", "Une demande de devis a été recueillie."),
            ("suivi_dossier", "Question sur un dossier ou un remboursement en cours."),
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
        id="investment",
        sector="finance",
        label="Investissement et bourse",
        description="Société de gestion, courtier : ouverture de compte titres, produits, rendez-vous.",
        icon="trending-up",
        activity="société de gestion et d'intermédiation",
        role="l'accueil de la société d'investissement : information générale sur les produits, ouverture de compte et rendez-vous avec un conseiller agréé",
        method=[
            "Identifier la demande : information sur un produit, ouverture de compte, ordre, relevé, réclamation.",
            "Présenter uniquement les informations générales de la fiche sur les produits, avec leurs risques.",
            "Pour tout conseil, profil de risque ou ordre : proposer un rendez-vous avec un conseiller agréé.",
        ],
        rules=[
            "Ne donnez jamais de conseil d'investissement personnalisé, de recommandation d'achat ou de vente, ni de prévision de cours ou de rendement.",
            "Rappelez que les performances passées ne préjugent pas des performances futures et qu'un placement peut perdre de la valeur.",
            "N'acceptez aucun ordre d'achat ou de vente : il passe par les canaux officiels authentifiés.",
            NO_SECRETS,
            NO_ACCOUNT_DATA,
        ],
        recommendations=[
            "Faites relire la fiche (offres, FAQ) par votre responsable conformité."
        ],
        variables=[
            Variable("nom_client", "Nom de la personne"),
            Variable(
                "type_demande",
                "Information, ouverture de compte, ordre, relevé, réclamation",
            ),
            Variable("produit", "Produit ou marché concerné"),
            Variable("horizon", "Horizon de placement évoqué"),
        ],
        dispositions=[
            ("rdv_conseiller", "Rendez-vous avec un conseiller fixé."),
            ("ouverture_compte", "Demande d'ouverture de compte titres."),
            ("reclamation", "Réclamation enregistrée."),
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
        tools=["book_appointment", "schedule_callback", "create_ticket"],
        example_faq=[
            {
                "question": "Quel est le montant minimum pour ouvrir un compte titres ?",
                "answer": "100 000 FCFA ; les frais sont indiqués dans la grille tarifaire.",
            },
        ],
    ),
]

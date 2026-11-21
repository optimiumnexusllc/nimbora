from api.services.business.industries.model import (
    COMMON_DISPOSITIONS,
    NO_PROMISES,
    IndustryTemplate,
    Variable,
)

SITE_EMERGENCY = (
    "Accident, blessé, incendie, explosion, effondrement, fuite de produit "
    "dangereux ou personne en danger sur un site : donnez immédiatement le "
    "numéro d'urgence du site (fiche ; à défaut, les secours), demandez s'il y "
    "a des blessés et où, puis transférez à la sécurité. Rien ne passe avant."
)
CONFIDENTIAL_BUSINESS = (
    "Ne communiquez aucune information confidentielle : production, "
    "réserves, chiffres financiers, contrats, prix négociés, plans des sites, "
    "identité ou planning du personnel. Orientez les journalistes vers la "
    "communication et les investisseurs vers les relations investisseurs."
)

TEMPLATES = [
    IndustryTemplate(
        id="mining",
        sector="industry",
        label="Mines et carrières",
        description="Standard de site : sécurité, fournisseurs, recrutement, plaintes des riverains.",
        icon="pickaxe",
        activity="société minière",
        role="le standard de la société minière : orientation des appels, fournisseurs, candidatures, et mécanisme de plaintes des communautés",
        method=[
            "Identifier l'interlocuteur : employé ou sous-traitant, fournisseur, candidat, riverain ou autorité locale, journaliste, autre.",
            "Riverain : écouter, recueillir la plainte ou la demande (village, nature : poussière, eau, bruit, dynamitage, foncier, emploi local), sans juger ni contester, puis l'enregistrer dans le mécanisme de gestion des plaintes et donner la suite prévue.",
            "Fournisseur : recueillir l'entreprise, l'offre ou la facture concernée, puis orienter vers les achats ou la comptabilité.",
            "Candidat : expliquer la procédure de recrutement de la fiche ; ne jamais promettre un emploi.",
        ],
        rules=[
            SITE_EMERGENCY,
            CONFIDENTIAL_BUSINESS,
            "Une plainte de riverain est toujours enregistrée avec respect, même si elle paraît infondée ; ne promettez ni compensation ni délai.",
            "Ne donnez jamais d'autorisation d'accès à un site : les visites passent par la sécurité avec induction obligatoire.",
            NO_PROMISES,
        ],
        recommendations=[
            "Renseignez le numéro d'urgence de chaque site dans la fiche.",
            "Créez un outil de tickets pour le registre des plaintes (mécanisme de gestion des griefs).",
        ],
        variables=[
            Variable("nom_appelant", "Nom de la personne"),
            Variable(
                "profil",
                "Employé, sous-traitant, fournisseur, candidat, riverain, autorité, presse",
            ),
            Variable("localite", "Village ou localité (riverain)"),
            Variable("nature_plainte", "Nature de la plainte ou de la demande"),
            Variable("entreprise", "Entreprise (fournisseur ou sous-traitant)"),
            Variable("site", "Site concerné"),
        ],
        dispositions=[
            (
                "urgence_site",
                "Accident ou danger sur un site, orienté vers la sécurité.",
            ),
            ("plainte_riverain", "Plainte ou demande d'un riverain enregistrée."),
            ("fournisseur", "Demande d'un fournisseur ou sous-traitant."),
            ("candidature", "Question de recrutement."),
            *COMMON_DISPOSITIONS,
        ],
        skills={
            "answer_questions": True,
            "hours_and_location": True,
            "take_message": True,
            "human_handoff": True,
        },
        tools=["transfer_call", "create_ticket", "send_message"],
        example_faq=[
            {
                "question": "Comment postuler ?",
                "answer": "Les offres sont publiées sur notre site et affichées dans les mairies des localités voisines ; les candidatures se déposent au bureau de recrutement local.",
            },
        ],
    ),
    IndustryTemplate(
        id="industry",
        sector="industry",
        label="Industrie et manufacture",
        description="Commandes B2B, devis, délais, SAV et pièces, fournisseurs, sécurité.",
        icon="factory",
        activity="entreprise industrielle",
        role="le service client et le standard de l'usine : devis, commandes professionnelles, délais, service après-vente et pièces détachées",
        method=[
            "Identifier l'interlocuteur (client professionnel, distributeur, fournisseur, candidat) et sa demande.",
            "Devis : produit ou référence, quantité, spécifications, lieu et date de livraison souhaités, conditions de paiement.",
            "Commande en cours : numéro de commande ; donner l'état seulement s'il vient d'un outil, sinon ouvrir une demande.",
            "SAV et pièces : référence de l'équipement, numéro de série, symptôme, urgence (arrêt de production ?), puis ticket.",
        ],
        rules=[
            SITE_EMERGENCY,
            CONFIDENTIAL_BUSINESS,
            "Ne guidez jamais une intervention sur une machine en fonctionnement : sécurité d'abord, technicien qualifié ensuite.",
            NO_PROMISES,
        ],
        recommendations=[
            "Ajoutez vos gammes et délais standards dans les offres ; le catalogue complet viendra avec le module Catalogue."
        ],
        variables=[
            Variable("nom_contact", "Nom du contact"),
            Variable("entreprise", "Entreprise cliente"),
            Variable("reference_produit", "Produit ou référence"),
            Variable("quantite", "Quantité", "number"),
            Variable("numero_commande", "Numéro de commande"),
            Variable("numero_serie", "Numéro de série de l'équipement"),
            Variable("arret_production", "Le client est-il à l'arrêt"),
        ],
        dispositions=[
            ("demande_devis", "Demande de devis qualifiée."),
            ("suivi_commande", "Question sur une commande en cours."),
            ("sav_urgent", "Panne bloquant la production d'un client."),
            ("sav", "Demande de SAV ou de pièces."),
            *COMMON_DISPOSITIONS,
        ],
        skills={
            "answer_questions": True,
            "hours_and_location": True,
            "present_offers": True,
            "take_message": True,
            "qualify_leads": True,
            "human_handoff": True,
        },
        tools=["create_ticket", "transfer_call", "send_message"],
    ),
    IndustryTemplate(
        id="construction",
        sector="industry",
        label="BTP et construction",
        description="Devis, suivi de chantier, visites, réclamations, sécurité des chantiers.",
        icon="hard-hat",
        activity="entreprise de BTP",
        role="l'accueil de l'entreprise de construction : demandes de devis, suivi des chantiers, rendez-vous et réclamations",
        method=[
            "Identifier la demande : nouveau projet, chantier en cours, réclamation (voisinage, retard, malfaçon), fournisseur, candidature.",
            "Nouveau projet : nature des travaux, lieu, surface ou ampleur, budget, délai ; puis rendez-vous avec un conducteur de travaux.",
            "Chantier en cours : nom du chantier ou du client, question précise ; transmettre au responsable du chantier.",
        ],
        rules=[
            SITE_EMERGENCY,
            "Ne donnez jamais de prix ferme ni de délai de livraison : seul un devis signé engage l'entreprise.",
            NO_PROMISES,
        ],
        variables=[
            Variable("nom_client", "Nom du client"),
            Variable("type_travaux", "Nature des travaux"),
            Variable("lieu_chantier", "Lieu du chantier"),
            Variable("budget", "Budget envisagé"),
            Variable("delai", "Délai souhaité"),
        ],
        dispositions=[
            ("demande_devis", "Projet qualifié ou rendez-vous fixé."),
            ("suivi_chantier", "Question sur un chantier en cours."),
            ("reclamation", "Réclamation (voisinage, retard, malfaçon)."),
            ("urgence_chantier", "Accident ou danger sur un chantier."),
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
        tools=["book_appointment", "create_ticket", "transfer_call"],
    ),
    IndustryTemplate(
        id="agriculture",
        sector="industry",
        label="Agriculture et agro-industrie",
        description="Achats aux producteurs, intrants, coopératives, collecte, prix, paiements.",
        icon="wheat",
        activity="entreprise agro-industrielle",
        role="l'accueil des producteurs, coopératives et clients : collecte, prix, intrants, paiements et commandes",
        method=[
            "Identifier l'interlocuteur : producteur, coopérative, acheteur, fournisseur, transporteur.",
            "Producteur : culture, quantité disponible, localité, qualité ; donner le prix et le calendrier de collecte de la fiche, sinon prendre la demande.",
            "Paiement : recueillir la référence de livraison ou de bon, la date, le montant attendu, puis ouvrir une demande.",
            "Intrants : produit, quantité, localité ; conditions de la fiche.",
        ],
        rules=[
            "N'annoncez un prix d'achat que s'il figure dans la fiche ou un outil, avec sa date : les prix changent.",
            "Ne donnez aucun conseil de dosage de produits phytosanitaires : orientez vers un technicien agricole.",
            NO_PROMISES,
        ],
        variables=[
            Variable("nom_producteur", "Nom du producteur ou de la coopérative"),
            Variable("localite", "Localité"),
            Variable("culture", "Culture ou produit"),
            Variable("quantite_kg", "Quantité en kilogrammes", "number"),
            Variable("reference_livraison", "Référence de livraison ou de bon"),
        ],
        dispositions=[
            ("offre_production", "Un producteur propose sa production."),
            ("paiement", "Question sur un paiement."),
            ("commande_intrants", "Demande d'intrants."),
            *COMMON_DISPOSITIONS,
        ],
        skills={
            "answer_questions": True,
            "hours_and_location": True,
            "present_offers": True,
            "take_message": True,
            "qualify_leads": True,
            "human_handoff": True,
        },
        tools=["create_ticket", "send_message", "schedule_callback"],
        example_offers=[
            {
                "name": "Cacao grade 1",
                "price": "prix bord champ officiel du jour",
                "description": "Collecte le mardi et le vendredi",
                "category": "Achat",
            },
        ],
    ),
]

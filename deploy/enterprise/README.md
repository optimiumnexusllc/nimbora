# NIMBORA : centre d'appels IA + humain, multi-entreprises, auto-hébergé

Cette édition transforme NIMBORA (plateforme open source d'agents vocaux, licence BSD-2)
en **plateforme SaaS** : plusieurs entreprises s'abonnent, chacune dispose de ses agents
IA, de ses files d'attente et de ses agents humains, et tout tourne sur **votre** serveur.

| Brique | Rôle | Technologie |
|---|---|---|
| Agents vocaux IA | Conversations téléphoniques, éditeur de workflows, campagnes | NIMBORA (FastAPI + Next.js + Pipecat) |
| Abonnements | Offres, essai gratuit, quotas de minutes, paiement | Module `saas` + Stripe (optionnel) |
| IA locale | LLM, reconnaissance et synthèse vocales sans cloud | Ollama/vLLM, Speaches (faster-whisper, Kokoro, Piper) |
| Centre d'appels humain | Files d'attente, postes d'agents, softphone navigateur | Asterisk 22 (PJSIP, app_queue, WebRTC) |
| Accès | HTTPS automatique, WebRTC | Caddy (Let's Encrypt), coturn |

## 1. Choisir le serveur

| Usage | Ressources conseillées |
|---|---|
| Démo, 1 à 3 appels simultanés, IA sur CPU | 8 vCPU, 32 Go RAM, 100 Go SSD |
| Production, 10 à 20 appels simultanés | Serveur avec GPU NVIDIA 24 Go (L4, RTX 4090, A10), 16 vCPU, 64 Go RAM |
| Au-delà | Séparer l'IA (serveur GPU) de la plateforme : `LOCAL_LLM_BASE_URL` / `LOCAL_SPEECH_BASE_URL` |

> Un VPS sans GPU fait tourner toute la plateforme, mais un LLM 7B sur CPU répond en
> plusieurs secondes : correct pour tester, trop lent pour un vrai centre d'appels.
> Avec un GPU, la latence de réponse descend sous la seconde.

Système : Ubuntu 22.04/24.04 ou Debian 12. Un nom de domaine dont l'enregistrement A
pointe vers l'IP du serveur.

## 2. Installer

```bash
git clone <votre-dépôt> /opt/nimbora && cd /opt/nimbora/deploy/enterprise
sudo ./install.sh --domain callcenter.mondomaine.com --email admin@mondomaine.com
# serveur GPU : ajouter --gpu
```

Le script installe Docker si besoin, génère tous les secrets dans `.env` (jamais de mot de
passe par défaut), configure le pare-feu, construit les images, démarre la plateforme et
télécharge les modèles d'IA (plusieurs Go, prévoir 10 à 30 minutes).

Créez ensuite votre compte sur `https://callcenter.mondomaine.com`, puis donnez-lui les
droits d'opérateur :

```bash
./scripts/make_superuser.sh vous@mondomaine.com
```

## 3. Gérer les abonnements (opérateur)

Console : **Superadmin → Clients et abonnements** (`/superadmin/tenants`).

- Trois offres sont créées au premier démarrage (Starter 99 €, Business 399 €,
  Enterprise 1 499 € HT/mois). Prix, minutes et identifiants Stripe se modifient dans
  la console ; vos changements ne sont jamais écrasés.
- Chaque nouvelle entreprise démarre en **essai gratuit** (`SAAS_TRIAL_DAYS`, 14 jours).
- Pour chaque client : changer d'offre, suspendre, prolonger, fixer des limites sur
  mesure (minutes, appels simultanés, agents IA, postes humains, campagnes).
- Les appels sont refusés automatiquement si l'essai est terminé, si l'abonnement est
  suspendu, si un paiement est en retard au-delà de `SAAS_GRACE_DAYS`, ou si les minutes
  incluses sont épuisées (sauf offre active avec dépassement facturé).

### Paiement en ligne avec Stripe (optionnel)

1. Dans Stripe, créez un produit et un prix mensuel par offre ; copiez les `price_…`
   dans la console opérateur.
2. Ajoutez un webhook vers `https://VOTRE_DOMAINE/api/v1/saas/stripe/webhook` avec les
   événements `checkout.session.completed`, `customer.subscription.*`, `invoice.paid`,
   `invoice.payment_failed`.
3. Renseignez `STRIPE_SECRET_KEY` et `STRIPE_WEBHOOK_SECRET` dans `.env`, puis
   `docker compose up -d api`.

Les clients choisissent alors leur offre dans **Abonnement** et gèrent leurs factures
dans le portail Stripe. Sans Stripe, vous attribuez les offres depuis la console et
facturez comme vous le souhaitez.

## 4. IA locale, langues et voix

Chaque nouvelle entreprise reçoit automatiquement une configuration « IA locale » :
LLM `LOCAL_LLM_MODEL` via Ollama, reconnaissance vocale Whisper large-v3-turbo et voix
dans la langue `LOCAL_DEFAULT_LANGUAGE`. Aucune clé d'API, aucune donnée ne sort.

| Langue | Compréhension (STT) | Voix (TTS) |
|---|---|---|
| Français | ✅ | Kokoro « Siwis », Piper « Siwis », « Tom », « UPMC » |
| Anglais, espagnol, portugais, italien, hindi, chinois, japonais | ✅ | Kokoro |
| Allemand, arabe, swahili, russe, turc | ✅ | Piper |
| Haoussa, yoruba, lingala, amharique, somali, shona, malgache | ✅ | à ajouter (réponse en français par défaut) |

Ajouter une langue ou une voix : éditez `api/services/local_ai/language_packs.py`
(une entrée par langue), reconstruisez (`docker compose build api && docker compose up -d`)
puis `./scripts/pull_models.sh`. Vérifiez la licence de chaque voix Piper sur sa fiche
Hugging Face avant un usage commercial (Kokoro est sous Apache 2.0).

Changer de LLM : `LOCAL_LLM_MODEL=llama3.1:8b` (ou `mistral-nemo`, `qwen2.5:14b-instruct`
sur GPU) dans `.env`, puis `./scripts/pull_models.sh`. Les entreprises peuvent aussi
brancher leurs propres fournisseurs (OpenAI, Deepgram, ElevenLabs…) dans *Providers*.

## 5. Centre d'appels humain

Dans **Centre d'appels** (`/contact-center`), chaque entreprise :

1. crée des **postes** (nom + numéro de poste) ; le mot de passe SIP s'affiche une fois ;
2. crée des **files d'attente** (`support`, `ventes`…) et y affecte des agents ;
3. dans un agent IA, ajoute l'outil **Transférer l'appel** avec la destination
   `queue:support` : l'IA passe la main à un humain quand c'est nécessaire.

Les agents se connectent au **softphone intégré** (page Centre d'appels, bouton
« C'est mon poste ») ou à tout softphone WebRTC (`wss://VOTRE_DOMAINE/sip`).
Codes : `*45` pause, `*46` reprise. Un agent ne peut appeler que les postes de sa propre
entreprise (aucune sortie vers le réseau téléphonique : pas de fraude possible).

### Brancher votre opérateur téléphonique (trunk SIP)

1. Déclarez le trunk dans `asterisk/pjsip_trunks.conf` (exemple OVH, Twilio Elastic SIP,
   Telnyx… avec `context=from-trunk`), puis `docker compose restart asterisk`.
2. **Numéros entrants** : dans `asterisk/extensions_custom.conf`, associez chaque numéro
   à l'application Stasis de l'entreprise qui le possède (affichée dans sa configuration
   Téléphonie, type « Asterisk ARI », adresse `http://asterisk:8088`, utilisateur `nimbora`).
3. Restreignez le port 5060 aux IP de votre opérateur : `ufw allow from <IP> to any port 5060`.

> Sécurité : les identifiants ARI de la plateforme donnent le contrôle de tous les appels
> d'Asterisk. C'est l'opérateur qui crée les configurations « Asterisk ARI » des
> entreprises ; ne communiquez jamais ce mot de passe à vos clients. En mode SaaS, la
> plateforme refuse les destinations brutes (`PJSIP/…`, `Local/…`) pour qu'une entreprise
> ne puisse pas joindre les postes d'une autre.

## 6. Exploitation

| Tâche | Commande |
|---|---|
| État des services | `docker compose ps` |
| Journaux | `docker compose logs -f api` |
| Sauvegarde (base + enregistrements + config) | `./scripts/backup.sh` (cron conseillé, voir l'en-tête du script) |
| Vérifier une sauvegarde | `./scripts/restore.sh /var/backups/nimbora/AAAAMMJJ-HHMMSS --check` |
| Restauration | `./scripts/restore.sh /var/backups/nimbora/AAAAMMJJ-HHMMSS` |
| Mise à jour | `git pull && docker compose build && docker compose up -d` (migrations automatiques) |
| Console Asterisk | `docker compose exec asterisk asterisk -rvvv` |

Dans `backup.env` (à côté de `docker-compose.yml`) : `BACKUP_PASSPHRASE_FILE` chiffre les
archives (AES-256), `BACKUP_RSYNC_TARGET` copie chaque sauvegarde hors du serveur,
`KEEP_DAYS` règle la rétention. Chaque sauvegarde a son `SHA256SUMS` ; la restauration
refuse une sauvegarde altérée. Avec le node exporter, la fraîcheur de la dernière sauvegarde
alimente l'alerte Prometheus `PlatformBackupTooOld` (voir `deploy/observability`).

## 7. Sécurité intégrée

- Démarrage refusé en mode SaaS si `OSS_JWT_SECRET` est faible ou par défaut, si le
  webhook Stripe n'est pas signé, ou si le mot de passe ARI manque.
- Isolation des entreprises : toutes les requêtes sont filtrées par organisation ; les
  noms Asterisk embarquent l'identifiant de l'entreprise et la configuration générée est
  assainie (aucune injection possible via les noms).
- Protection SSRF : une entreprise ne peut pas faire appeler par la plateforme des
  adresses internes (base de données, Redis, MinIO, ARI, métadonnées cloud). Seules les
  URL de modèles vers `ollama`, `speaches` et `vllm` sont autorisées, jamais pour les outils HTTP.
- Seuls 80/443, SIP/RTP et TURN sont exposés ; Postgres, Redis, MinIO, l'API, Ollama et
  Speaches restent sur le réseau Docker privé.
- Mots de passe SIP des agents : seul le condensat digest est stocké.
- Télémétrie désactivée : aucune donnée envoyée à des tiers.

## 8. Limites connues de cette version

- Le routage des numéros entrants vers les entreprises se fait dans
  `extensions_custom.conf` (pas encore depuis l'interface).
- La base de connaissances (RAG) attend des embeddings de 1 536 dimensions : en 100 %
  local, servez un modèle compatible (par ex. `Alibaba-NLP/gte-Qwen2-1.5B-instruct`) via un
  serveur compatible OpenAI, ajoutez son nom d'hôte à `SERVICE_URL_ALLOWED_HOSTS` et
  déclarez-le comme fournisseur « OpenRouter » avec son URL.
- Les nouvelles pages (Abonnement, Centre d'appels, console opérateur) sont en français,
  le reste de l'interface NIMBORA est en anglais.

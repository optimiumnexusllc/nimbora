# PBX d'entreprise en marque blanche

Ce kit installe, sur un serveur dédié, le moteur de communication unifiée qui sert de
**PBX d'entreprise** à NIMBORA : postes et lignes SIP, files d'attente, agents, serveurs
vocaux, messageries, conférences, journaux d'appels. Le moteur est
[Wazo Platform](https://github.com/wazo-platform) (GPL-3.0), rebrandé intégralement : vos
clients, leurs employés et leurs téléphones ne voient que votre marque.

```
             Internet / opérateurs SIP
                       │
        ┌──────────────▼───────────────┐            ┌────────────────────────┐
        │  PBX (ce kit, Debian 12)     │  REST API  │  NIMBORA               │
        │  postes, files, agents, IVR  │◄───────────┤  console, agents IA,   │
        │  Asterisk ── ARI :5039 ──────┼───────────►│  supervision, mémoire  │
        │        └─ audio IA (wss) ────┼───────────►│  client, rapports      │
        │  webhooks d'événements ──────┼───────────►│                        │
        └──────────────────────────────┘            └────────────────────────┘
```

- **Pilotage** : NIMBORA appelle les API REST du PBX avec un compte de service aux
  droits minimaux (`integration-policy.json`, 110 ACL précises, aucun joker global ; relancer `scripts/create_service_account.py` après une mise à jour de NIMBORA met la politique à jour sans changer le mot de passe).
- **Agents IA** : un numéro du PBX est routé vers `Stasis(<app>,inbound,called=<numéro>)` ;
  NIMBORA reçoit l'appel par ARI et diffuse l'audio de l'agent IA par WebSocket.
- **Événements** : le PBX envoie à NIMBORA les fins d'appel ; les appels humains
  rejoignent l'historique client, à côté des appels IA, de WhatsApp et du chat web.

## 1. Prérequis

| | |
|---|---|
| Serveur | Debian 12 (bookworm) **vierge**, 4 vCPU, 8 Go RAM, 50 Go SSD (jusqu'à ~100 postes) |
| Réseau | IP publique ou privée joignable par NIMBORA ; ports SIP/RTP ouverts vers vos opérateurs |
| NIMBORA | Accessible en HTTPS depuis le PBX (audio des agents IA en `wss://`) |
| Nom | Un nom DNS pour le PBX (ex. `pbx.votre-marque.com`) |

Un serveur dédié est nécessaire : le moteur installe son propre Asterisk, PostgreSQL,
RabbitMQ et nginx, et ne cohabite pas avec Docker ni avec la pile NIMBORA.

## 2. Installer

```bash
git clone <votre-dépôt> /opt/nimbora && cd /opt/nimbora/deploy/pbx
sudo ./install.sh \
  --brand "NIMBORA" \
  --nimbora-url https://app.votre-marque.com \
  --nimbora-ip 203.0.113.10 \
  --company "Ivoire Immo"
```

| Option | Rôle |
|---|---|
| `--brand` | Nom de la plateforme (e-mails, page d'accueil, bannière) |
| `--pbx-name` | Nom commercial du PBX (défaut : « `<brand>` Voice ») ; donne aussi l'agent SIP |
| `--nimbora-url` | Adresse de NIMBORA (lien de réinitialisation, audio des agents IA) |
| `--nimbora-ip` | Seule IP autorisée à joindre l'ARI (port 5039) |
| `--company` | Nom du premier tenant (l'entreprise cliente) |
| `--support-email`, `--noreply-email` | Expéditeur et contact des e-mails (défaut : domaine de NIMBORA) |
| `--ari-tls-cert`, `--ari-tls-key` | Chiffre l'ARI en HTTPS — **obligatoire** si NIMBORA joint le PBX par Internet |
| `--engine-version` | Version du moteur (défaut : dernière stable, ex. `26.09`) |

Le script :

1. génère **tous** les secrets dans `/etc/nimbora-pbx/secrets.env` (root uniquement) :
   l'installateur du moteur a des mots de passe **publics** par défaut (ARI, AMI, base de
   données), ils ne sont jamais utilisés ;
2. installe la **dernière version stable** du moteur (`pelican-bookworm`, version épinglée
   par l'étiquette de l'installateur), **sans son interface web** ;
3. applique la **marque blanche** (`whitelabel.yml`, détail ci-dessous) ;
4. ferme l'ARI (5039) à tout sauf NIMBORA et l'AMI (5038) à tout sauf le serveur lui-même,
   en IPv4 comme en IPv6 ;
5. crée le **compte de service** `nimbora-integration` dans le tenant de l'entreprise ;
6. affiche les valeurs à saisir dans NIMBORA.

## 3. Relier à NIMBORA

1. **Téléphonie → Ajouter → Asterisk ARI** : endpoint `http(s)://<pbx>:5039`, utilisateur
   `xivo`, mot de passe `ARI_PASSWORD`, client WebSocket `nimbora`. Notez le nom
   d'application Stasis généré.
2. **Téléphonie d'entreprise → Connexion** : adresse `https://<pbx>`, compte
   `nimbora-integration`, mot de passe `SERVICE_PASSWORD`, tenant, et la configuration
   ARI de l'étape 1. NIMBORA vérifie aussitôt les accès et la version.
3. **Appliquer la marque** (agent SIP) et **Recevoir les événements** (historique des
   appels humains).
4. **Router un numéro vers un agent IA** : NIMBORA crée le numéro entrant sur le PBX et
   l'enregistre de son côté. Un numéro qui a déjà une destination (poste, file…) n'est
   jamais écrasé.

## 4. Ce que la marque blanche change

| Élément visible | Avant | Après |
|---|---|---|
| E-mail de réinitialisation du mot de passe | expéditeur `wazo-auth <noreply@wazo.community>`, texte « Wazo », lien vers `app.wazo.io` | expéditeur `<pbx-name> <noreply@votre-domaine>`, texte en français, lien vers `<nimbora-url>/pbx-password` |
| E-mail de confirmation d'adresse | « wazo-auth » | votre marque, page de confirmation à vos couleurs |
| En-têtes SIP `User-Agent` / `Server` (vus par les opérateurs et les téléphones) | `Wazo` | `<pbx-name>` (ex. `NIMBORA-Voice`) |
| Interface web du moteur | `wazo-ui` | non installée : tout passe par NIMBORA |
| Page d'accueil HTTPS du serveur, bannière SSH | moteur | votre marque |

La page `/pbx-password` de NIMBORA ne relaie une réinitialisation qu'à un PBX déjà connu :
l'hôte présent dans le lien de l'e-mail ne sert qu'à choisir parmi vos PBX (pas de SSRF).

**À traiter selon votre parc** (voir la feuille de route) : écrans des téléphones
provisionnés (`wazo-provd`), messages vocaux et musique d'attente, applications mobiles et
de bureau, authentification externe (Google, Microsoft) qui passe par un service du
fournisseur du moteur.

## 5. Licence et marque

- Le moteur est sous **GPL-3.0**. Le kit ne modifie pas son code : il le configure et
  remplace des gabarits par les nôtres. Les fichiers `LICENSE` et les mentions de
  copyright du moteur restent installés sur le serveur. Si vous redistribuez des paquets
  **modifiés** du moteur, vous devez fournir leurs sources sous GPL-3.0.
- NIMBORA (BSD-2) dialogue avec le moteur par le réseau : ce sont deux programmes
  distincts, sans effet de la GPL sur NIMBORA.
- « Wazo » est une marque de son titulaire : la retirer de ce que voient vos clients est
  précisément ce que fait la marque blanche. Gardez la mention du moteur dans vos
  documents juridiques (`NOTICE.md`).

## 6. Exploitation

```bash
wazo-service status                      # état des services du moteur
cat /etc/nimbora-pbx/secrets.env         # secrets (root)
ansible-playbook -i /opt/nimbora-pbx/inventory.ini whitelabel.yml \
  -e @/etc/nimbora-pbx/branding.yml      # réappliquer la marque (après une mise à jour)
```

Après chaque mise à jour du moteur, relancez `whitelabel.yml` : un paquet peut réinstaller
ses gabarits ou sa page d'accueil.

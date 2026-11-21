# Journal de validation — phase 5 sur un seul serveur (laboratoire)

Validation du PBX d'entreprise en marque blanche (phase 5 de la feuille de route) avec le
kit [`deploy/lab/`](../../deploy/lab/README.md) : PBX dans un conteneur Incus Debian 12 et
plateforme NIMBORA en Docker Compose derrière le Traefik existant, sur **un seul VPS déjà
occupé** par d'autres services, qui ne doivent pas être touchés.

Légende : ✅ vérifié · ❌ échec · 🧪 non vérifié (raison indiquée) · 🐛 bogue trouvé et corrigé.

## Rapport d'étape 1 — inventaire (21 novembre 2026)

**Serveur.** VPS Hostinger KVM, Ubuntu 24.04.5, noyau 6.8, 4 vCPU AMD EPYC, 15,6 Go de RAM
(10,7 Go disponibles), 193 Go de disque (116 Go libres), IPv4 publique unique. Docker 29 et
Compose v5.8, 15 conteneurs sains gérés par Coolify (Traefik v3.6 `coolify-proxy`, bases
PostgreSQL, umami, refprix, applications), plus Odoo/BQeen, Kaevorin (pm2), un bot de trading,
SentinelBlock et un PostgreSQL 16 et un Redis hôte en local.

**Constat.** UFW n'est plus installé (paquet à l'état `rc`, chaînes iptables vides, politique
INPUT `ACCEPT`) : le filtrage se fait désormais **dans le pare-feu de l'hébergeur**, en amont.
Décision : ne pas réinstaller UFW ; le kit documente la liste des ports à ouvrir chez
l'hébergeur et garde UFW en option (`--ufw`).

**Traefik.** Géré par Coolify ; fournisseur `file` avec `watch` sur
`/data/coolify/proxy/dynamic/`, résolveur Let's Encrypt par défi HTTP, réseau Docker `coolify`
(10.0.1.0/24). Odoo y est déjà routé par un fichier dynamique vers l'IP hôte : déposer un
fichier YAML suffit, sans redémarrer Traefik.

**Ports déjà pris** : 5432 et 6379 (hôte), 8000 (Coolify), 80/443 (Traefik). Libres : 5060,
5061, 10000-20000, 3478, 5349, 49152-49200.

**Domaines** : `app.optimiumnexus.com` et `pbx.optimiumnexus.com` pointent vers le serveur.

**Décision d'architecture.** Le kit `deploy/pbx/` exige un Debian 12 vierge sans Docker ; le
serveur est un Ubuntu mutualisé. Réinstaller l'hôte (option A) détruirait les autres services
et ne suffirait pas (NIMBORA a besoin de Docker). Retenu : PBX dans un **conteneur système
Incus** Debian 12 (2 vCPU, 4 Go), plateforme en Compose derrière Traefik, règles
`DOCKER-USER` pour la cohabitation Docker/Incus, DNAT RTP vers le conteneur, ARI jamais
exposé (réseau privé 10.250.0.0/24, `--nimbora-ip` = adresse de l'hôte sur le pont).

Snapshot A de l'hébergeur pris avant l'installation d'Incus.

## Rapport d'étape 2 — Incus, pare-feu, PBX, pile NIMBORA (21 novembre 2026)

État à la fin de l'étape : PBX installé et réglé dans le conteneur, pile NIMBORA démarrée
et saine, aucun service existant touché (15 conteneurs Coolify toujours `healthy`, Odoo,
Kaevorin et les autres processus inchangés), 7 Go de RAM encore disponibles. **Arrêt pour le
snapshot B** avant d'écrire dans le dossier dynamique de Traefik.

| Date | Action | Résultat |
|---|---|---|
| 21/11 13:15 | Construction des images `nimbora-api` et `nimbora-ui` depuis le dépôt (aucune image publiée sur ghcr.io ni Docker Hub) | ✅ 45 min, 4 vCPU |
| 21/11 13:27 | `install.sh --only preflight,incus,firewall,pbx` : Incus 6.0 installé, pont `incusbr0` 10.250.0.1/24, stockage `dir`, sysctl inotify | ✅ |
| 21/11 13:27 | Service `nimbora-lab-firewall` | ❌ puis ✅ après 🐛 n° 1 |
| 21/11 13:28 | Conteneur `nimbora-pbx` Debian 12 lancé, IP fixe 10.250.0.10, limites 2 vCPU / 4 Go | ✅ |
| 21/11 13:39 | `deploy/pbx/install.sh` dans le conteneur : moteur Wazo 26.11 installé (150 tâches), tous les services `wazo-service status` en marche, puis échec à « Create tenant » | ❌ 🐛 n° 2 |
| 21/11 13:45 | Asterisk 22.12.0 du moteur : `module show like websocket` → `chan_websocket.so` **Running**, `res_websocket_client.so` **Running**, `res_pjsip_transport_websocket.so` Running | ✅ ligne 🧪 « modules `chan_websocket` / `res_websocket_client` » |
| 21/11 13:50 | Relance `--only pbx` avec le correctif n° 2 : tenant « Entreprise test » créé, marque blanche appliquée (en-tête SIP `NIMBORA-Voice`, page d'accueil « NIMBORA Voice »), nftables ARI/AMI, compte de service `nimbora-integration` à **110 ACL** | ✅ |
| 21/11 15:25 | `pbx_nat.py` : `external_media_address` et `external_signaling_address` = IP publique, `local_net` 10.250.0.0/24 sur `transport-udp` et `transport-wss`, RTP 10000-20000 confirmé (`rtp show settings`), Asterisk redémarré | ✅ |
| 21/11 15:40 | `install.sh --only nimbora` : `.env` généré, override Compose, `docker compose up` | ❌ 🐛 n° 3 (image MinIO) puis ✅ |
| 21/11 15:55 | Pile saine : postgres, redis, minio, api (`/api/v1/health` → `ok`, 1.51.0), ui, coturn (3478/5349 TCP+UDP, 49152-49200/udp publiés) ; aucun autre port publié | ✅ |
| 21/11 16:00 | API → ARI du PBX (`10.250.0.10:5039`) | ❌ 🐛 n° 5 puis ✅ (401 = joignable, authentification attendue) |
| 21/11 16:00 | ARI depuis un conteneur d'un autre réseau Docker (`coolify`) | ✅ bloqué (règle 8 de `DOCKER-USER`) |
| 21/11 16:00 | PBX → `https://app.<domaine>` par Traefik (épingle à cheveux) | ✅ 503 de Traefik, attendu avant la phase traefik : le chemin réseau fonctionne |
| 21/11 16:00 | API → `https://10.250.0.10` (nginx du moteur, certificat auto-signé) | ✅ répond |

Services existants pendant l'étape : 15 conteneurs toujours `healthy`, mémoire disponible
10,7 Go avant la pile NIMBORA, 7,0 Go après (conteneur PBX : 1,6 Go pendant l'installation).

### 🐛 n° 3 — images MinIO introuvables (bloque toute installation neuve)

**Symptôme** : `docker compose up` → `quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z` :
`401 UNAUTHORIZED` ; `minio/minio` sur Docker Hub : `pull access denied` ; `minio/minio:latest`
et `quay.io/minio/minio:latest` absents aussi. MinIO a retiré ses images publiques.
**Correction** (`docker-compose.yaml`, `docker-compose-local.yaml`,
`deploy/enterprise/docker-compose.yml`) : image par défaut `bitnamilegacy/minio:2025.4.22`,
build Bitnami de **la même version** (binaire `minio DEVELOPMENT.2025-04-22T22-12-26Z`, `mc`
inclus). L'image Bitnami est prévue pour l'utilisateur 1001 sous `/bitnami` : elle tourne en
root avec `minio server /data` pour garder la disposition officielle et les volumes
existants ; la variable `MC_HOST_local` fournit l'alias du contrôle de santé `mc ready local`
que l'image officielle définissait seule. `MINIO_IMAGE` reste surchargeable. Vérifié par un
conteneur d'essai (`mc ready local` → « The cluster 'local' is ready ») puis par la pile.
Test : `test_minio_image_is_pullable_and_health_check_has_its_alias`.

### 🐛 n° 4 — fichier de secrets par défaut ignoré selon les phases jouées

**Symptôme** : `--only nimbora` affiche « Aucun fichier de secrets () ».
**Cause** : le chemin par défaut (`/etc/nimbora-lab/secrets.env`) n'était calculé que dans la
phase `preflight`. **Correction** : calculé pour toute exécution ; un fichier déposé plus
tard est repris au prochain `--only nimbora`.

### 🐛 n° 5 — l'ARI reste sur 127.0.0.1 malgré `b2bua_listen_address = 0.0.0.0`

**Symptôme** : depuis la plateforme, `10.250.0.10:5039` → `connection refused` ; dans le
conteneur, `ss -tlnp` montre `127.0.0.1:5039`.
**Cause** : le rôle `b2bua` du moteur n'écrit `/etc/asterisk/http.d/10-engine-api.conf` que si
`b2bua_listen_address` **et** `b2bua_port_http` sont définis ; le kit ne donnait que
l'adresse. Sur un serveur dédié, la plateforme n'aurait jamais pu joindre l'ARI.
**Correction** dans `deploy/pbx/install.sh` : `b2bua_port_http = 5039` dans l'inventaire ;
`b2bua_port_sysconfd` volontairement absent (wazo-sysconfd n'a pas d'authentification et
resterait sinon exposé sur la même adresse). Appliqué à chaud sur le PBX du laboratoire avec
le même fichier que celui du rôle, puis `module reload http`. Test :
`test_pbx_inventory_defines_ari_port_with_its_address`.

### Observation de sécurité (à traiter, non corrigée ici)

Dans le conteneur, plusieurs services du moteur écoutent sur toutes les interfaces :
RabbitMQ (5672, 25672, 4369 epmd), Postfix (25), `chan_skinny` (2000), wazo-phoned
(9498/9499), wazo-provd HTTP (8667), nginx (80/443). Au laboratoire, seuls Traefik (443) et la
plateforme atteignent le conteneur, et les autres réseaux Docker sont bloqués. Sur un
**serveur dédié exposé**, le kit `deploy/pbx/` ne filtre que l'ARI et l'AMI : les ports
ci-dessus dépendent du pare-feu de l'hébergeur. Amélioration proposée : étendre la table
nftables du kit à RabbitMQ, epmd, SCCP et SMTP (localhost seulement) et documenter la liste.

### 🐛 n° 1 — `firewall.sh` échoue au premier lancement

**Symptôme** : `nimbora-lab-firewall.service` sort en erreur, aucune règle posée.
**Cause** : avec `set -o pipefail`, le nettoyage des règles existantes
(`iptables -S … | grep -- "--comment nimbora-lab"`) échoue quand `grep` ne trouve rien, ce
qui est le cas normal au premier lancement.
**Correction** : `grep … || true` dans le pipeline. Test : `deploy/lab/tests/test_kits.py`.

### 🐛 n° 2 — nom d'entreprise avec espace refusé par l'installateur du moteur

**Symptôme** : `wazo-auth-cli tenant create Entreprise test` → code 2, playbook arrêté
(`failed=1`). L'exemple du README du kit, « Ivoire Immo », échoue de la même façon.
**Cause** : le rôle `uc-engine` du moteur interpole `{{ tenant_name }}` sans guillemets dans
un `command:` ; Ansible découpe le nom en deux arguments.
**Correction** dans `deploy/pbx/install.sh` : la valeur est écrite dans l'inventaire sous la
forme d'un littéral Python contenant les guillemets (`'"Ivoire Immo"'`), qu'Ansible évalue en
`"Ivoire Immo"` et que le module `command` garde en un seul argument ; les noms contenant un
guillemet sont refusés. Test : `test_tenant_name_with_space_is_one_argument` (évaluation
`ast.literal_eval` puis `shlex.split`, comme Ansible).

### Preuves

```
$ incus exec nimbora-pbx -- asterisk -rx "module show like websocket"
chan_websocket.so              Websocket Media Channel        0  Running  core
res_http_websocket.so          HTTP WebSocket Support         6  Running  core
res_pjsip_transport_websocket.so PJSIP WebSocket Transport    0  Running  core
res_websocket_client.so        WebSocket Client Support       2  Running  core
$ incus exec nimbora-pbx -- asterisk -rx "core show version"
Asterisk 22.12.0-1~wazo3.deb12
$ iptables -S DOCKER-USER | grep -c nimbora-lab      # 7 règles
$ iptables -t nat -S PREROUTING | grep nimbora-lab   # DNAT udp 10000:20000 → 10.250.0.10
```

## Rapport d'étape 3 — image MinIO figée, durcissement du PBX (21 novembre 2026)

Snapshot B pris. Deux corrections avant la phase Traefik.

**Image MinIO.** Vérification sur Docker Hub : le dépôt `bitnami/minio` existe mais n'expose
plus aucune étiquette publique (« Bitnami Secure Image », abonnement) ; `bitnamilegacy/minio`
est décrit « Legacy Bitnami images (no longer updated) », dernière mise à jour le
19 août 2025, étiquette `2025.4.22` poussée le 3 juillet 2025 (amd64 et arm64). Décision :
épingler cette étiquette **par digest** (`sha256:50cec18a…`) dans les trois fichiers compose,
et inscrire « stockage objet durable » à la feuille de route (image MinIO construite depuis les
sources, ou Garage / SeaweedFS). Test : `deploy/lab/tests/test_compose.py`.

**Pare-feu du PBX fermé par défaut** (`deploy/pbx/install.sh`, table `inet nimbora_pbx`,
politique `drop`) : bouclage local, réponses, ICMP et bail DHCP permis ; ouverts : SSH
(`--ssh-from`, défaut `any`), 443, SIP 5060/5061 et RTP (`--sip-from`, défaut `any`,
`--rtp-range`), ARI 5039 depuis l'IP NIMBORA et localhost, AMI 5038 localhost, provisioning
8667/9498/9499 seulement avec `--phones-from`. Nouvelle option `--firewall-only` pour
réappliquer après un changement d'options. Tests : rendu réel du fichier nftables par le
script (`test_pbx_firewall_*`), listes de sources valides et refusées.

| Vérification dans le conteneur après application | Résultat |
|---|---|
| `wazo-service status` : 18 services en marche | ✅ |
| Sortie Internet (`curl https://mirror.wazo.community/version/stable`) | ✅ 200 |
| Renouvellement du bail DHCP (`networkctl renew eth0`), adresse conservée | ✅ |
| API confd et wazo-auth par le nginx local (443) | ✅ |
| Depuis l'hôte (10.250.0.1) : 5672, 25672, 4369, 25, 2000, 8667, 9498, 80 | ✅ fermés (timeout) |
| Depuis l'hôte : 443 ouvert, ARI 5039 → 401 (IP NIMBORA autorisée) | ✅ |
| Depuis `nimbora_api` : 443 → 200, ARI → 401, 5672 → fermé | ✅ |

## Fournisseurs d'IA : combinaison à paliers gratuits (analyse du code, 21 novembre 2026)

Aucune clé n'est disponible pour cette validation. Les clés se saisissent **dans la console**
(Fournisseurs d'inférence → Ajouter une connexion), par organisation ; aucune variable
d'environnement ne les porte. Fournisseurs reconnus par le code (`ServiceProviders`,
`service_factory.py`) et utilisables sans carte bancaire :

| Rôle | Fournisseur | Dans le code | Palier gratuit |
|---|---|---|---|
| STT | Deepgram `nova-3` (ou Flux) | ✅ `deepgram`, clé d'API | crédit d'essai à l'inscription |
| LLM | Groq `llama-3.3-70b-versatile` | ✅ `groq`, clé d'API | palier gratuit (quotas par minute) |
| LLM | Google AI Studio `gemini-3.5-flash` | ✅ `google`, clé d'API AI Studio | palier gratuit |
| TTS | Deepgram Aura-2 | ✅ `deepgram`, même clé que le STT | même crédit |
| Tout-en-un | Gemini Live `gemini-3.8-live` (mode `realtime`) | ✅ `google_realtime`, clé AI Studio, voix et langue `fr` | palier gratuit |

Combinaison recommandée pour la validation : **Deepgram (STT + TTS) + Groq (LLM)**, ou
**Gemini Live seul** en mode temps réel (une seule clé, STT + LLM + TTS). Google STT et TTS
(`google`) demandent un compte de service Google Cloud avec facturation : à éviter ici.

Améliorations possibles, non implémentées :

- **Groq Whisper (STT)** : Groq n'est enregistré que comme LLM ; son API Whisper gratuite
  n'est pas disponible comme transcripteur.
- **Gemini TTS par AI Studio** : la synthèse `google` passe par Google Cloud TTS (compte de
  service) ; pas de variante AI Studio par clé.
- **Amorçage des connexions fournisseur** depuis un fichier de secrets au déploiement : le
  kit lab fusionne `/etc/nimbora-lab/secrets.env` dans le `.env` de la pile, mais les clés
  d'IA ne sont pas des variables d'environnement ; une amorce par l'API (`model_connections`)
  éviterait la saisie manuelle dans la console.

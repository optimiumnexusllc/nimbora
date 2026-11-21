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

## Rapport d'étape 4 — Traefik et certificats (21 novembre 2026)

`install.sh --only traefik` : fichier `nimbora-lab.yaml` déposé dans le dossier dynamique de
Traefik (les quatre fichiers Coolify sont inchangés), rechargé à chaud, certificats Let's
Encrypt obtenus en moins d'une minute par le défi HTTP.

| Vérification | Résultat |
|---|---|
| `app.optimiumnexus.com` : certificat Let's Encrypt (CN exact, valide 90 jours), HTTP → 301 HTTPS | ✅ |
| `pbx.optimiumnexus.com` : certificat Let's Encrypt, HTTP → 301 HTTPS | ✅ |
| `https://app…/api/v1/health` → `{"status":"ok","version":"1.51.0"}` ; `/` → page de connexion de la console | ✅ |
| `https://pbx…/` → page d'accueil « NIMBORA Voice » du moteur (TLS terminé par Traefik, nginx du moteur en amont avec son certificat auto-signé) | ✅ |
| `https://pbx…/api/auth/0.1/status` → 200 (API du moteur à travers Traefik) | ✅ |
| `wss://pbx…/api/asterisk/ws` : `Upgrade: websocket` + `Sec-WebSocket-Protocol: sip` en HTTP/1.1 → `101 Switching Protocols` (en HTTP/2, 426 : les clients SIP WebSocket négocient en HTTP/1.1) | ✅ |
| Routes existantes `coolify.<domaine>` et `bqeen.<domaine>` toujours servies, aucun message d'erreur Traefik | ✅ |
| Mémoire disponible après l'étape | 6,9 Go |

Commandes :

```
openssl s_client -servername pbx.optimiumnexus.com -connect <IP>:443 | openssl x509 -noout -issuer -dates
curl --http1.1 -i -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" -H "Sec-WebSocket-Protocol: sip" https://pbx.optimiumnexus.com/api/asterisk/ws
```

**Arrêt pour rapport** avant la liaison PBX ↔ NIMBORA.

## Rapport d'étape 5 — compte administrateur, fail2ban, liaison PBX ↔ NIMBORA (21 novembre 2026)

**Compte administrateur** créé en premier par l'API publique d'inscription (`contact@…`,
organisation 1), mot de passe initial dans un fichier local en lecture root seulement, jamais
dans le dépôt. Puis **inscription publique fermée** : `ENABLE_SIGNUP=false` dans le `.env` de
la pile, conteneur API recréé, `POST /api/v1/auth/signup` → 403, `/api/v1/health` →
`signup_enabled: false`. Le kit lab ne le fait pas encore automatiquement : amélioration
prioritaire notée (option `--admin-email` qui crée le compte puis ferme l'inscription).
Remarque : le nom passé à l'inscription n'est pas renvoyé par `/auth/me` (`name: null`), à
vérifier.

**fail2ban pour wazo-auth** dans le kit `deploy/pbx/` (commit `26fdd14`) : prison
`nimbora-pbx-auth` sur `/var/log/wazo-auth.log`, 5 échecs en 10 min → 1 h de bannissement
(443, 5060, 5061), à côté des prisons du moteur (`asterisk-wazo`, `wazo-provd`, `sshd`).
Vérifié sur le PBX : `fail2ban-regex` reconnaît les 2 échecs réels du journal, 5 prisons
actives, 18 services en marche. Point d'attention derrière un reverse proxy : wazo-auth voit
l'adresse du proxy (ici `10.250.0.1`, qui est aussi celle de la plateforme) ; les adresses de
NIMBORA (privée et publique, résolue depuis `--nimbora-url`) sont donc exclues du bannissement,
et `--trusted-proxy` fait journaliser l'adresse réelle du client par nginx. Un bannissement
d'adresse réelle n'a d'effet que sur les connexions directes : derrière Traefik, le blocage
devrait se faire côté proxy (amélioration).

**Liaison** (API de la plateforme, compte administrateur) :

| Étape | Résultat |
|---|---|
| Configuration téléphonie « Asterisk ARI » : `http://10.250.0.10:5039`, utilisateur `xivo`, client WebSocket `nimbora` | ✅ id 1 |
| Connexion Téléphonie d'entreprise : `https://10.250.0.10`, `nimbora-integration`, tenant « Entreprise test », certificat non vérifié, ARI n° 1 | ✅ `status: ok`, `engine_version: 26.11` |
| Test de connexion | ✅ |
| Appliquer la marque | ❌ 502 « accès refusé » → 🐛 n° 6 |
| Recevoir les événements (abonnement webhookd vers `https://app…/api/v1/pbx/events/<jeton>`) | ✅ `subscription_uuid` créé |
| Réglage softphones : `wss://pbx.optimiumnexus.com/api/asterisk/ws`, domaine SIP `pbx.optimiumnexus.com` | ✅ |
| Inventaire | ✅ vide au départ |
| Création des postes 1001 (WebRTC, agent) et 1002 (SIP) | ❌ 409 « Aucun contexte interne sur le PBX » → 🐛 n° 7, puis ✅ (agent n° 1 pour 1001) |
| File « Support test » 3000, stratégie `leastrecent`, membre : agent 1001 | ✅ |
| Supervision : écoute, chuchotement, intervention activés, superviseur = poste 1002, information des salariés confirmée | ✅ |

Identifiants des postes et procédure de test humain : fichier local `nimbora-lab-postes.txt`
(root seulement). Linphone mobile exige l'ouverture temporaire de 5060/udp chez l'hébergeur
et `--sip-public` sur l'hôte (le PBX n'a pas de transport TLS 5061 par défaut) ; sinon, deux
navigateurs avec le softphone web.

### 🐛 n° 6 — « Appliquer la marque » échoue en 502 avec le compte de service

**Symptôme** : `POST /api/v1/pbx/branding/apply` → 502 « PBX : accès refusé ». Journal
confd : `GET /asterisk/pjsip/global` → 401 pour le jeton du compte de service, alors que la
politique contient bien `confd.asterisk.pjsip.global.read/update`.
**Cause** : les réglages globaux d'Asterisk du moteur ne sont accessibles qu'avec un jeton du
tenant maître ; un compte de service d'entreprise (celui du kit, à droits minimaux) obtient
401 quelle que soit sa politique. Le kit pose déjà l'en-tête SIP à l'installation
(`whitelabel.yml`, vérifié : `User-Agent: NIMBORA-Voice`).
**Correction** (`api/services/pbx/service.py`) : l'erreur d'autorisation devient un compte
rendu `applied_by: kit` avec explication, sans 502 ; la console affiche ce message au lieu de
« Marque appliquée ». Tests : `test_branding_is_reported_as_the_kits_when_the_engine_refuses`
(faux PBX en mode « réglages globaux réservés au maître »).

### 🐛 n° 7 — le tenant n'a aucun contexte, impossible de créer un poste

**Symptôme** : `POST /api/v1/pbx/extensions` → 409 « Aucun contexte interne sur le PBX ».
`GET /confd/1.1/contexts` sur le tenant : aucun (le moteur en crée un, interne seulement, au
premier accès au tenant ; jamais d'entrant ni de sortant).
**Correction** (`deploy/pbx/scripts/ensure_tenant_contexts.py`, appelé par `install.sh`) :
création idempotente d'un contexte interne (postes 1000-1999, groupes 2000-2999, files
3000-3999, conférences 4000-4999), d'un contexte entrant (plages par longueur de numéro, 4 à
15 chiffres : le moteur exige début et fin de même longueur) et d'un contexte sortant inclus
par l'interne. Commit `4478631`, test `test_tenant_contexts_cover_what_the_platform_reads_by_type`.

## Rapport d'étape 6 — PBX partagé de l'opérateur, PR #1 `feat/lot-a-saas-tenants` (21 novembre 2026)

Branche récupérée, fusionnée avec `main` (trois conflits résolus : options du kit,
README du kit, page PBX de la console), images API et UI construites depuis la branche
(`REGISTRY=nimbora-lot-a` dans le `.env` du laboratoire pour les distinguer de celles de
`main`), migration `b5c6d7e8f9a0` appliquée au démarrage.

| Étape | Résultat |
|---|---|
| `create_service_account.py --provisioner` dans le conteneur : compte `nimbora-provisioning` dans le tenant principal, politique = intégration (110) + approvisionnement (11) = **121 ACL** | ✅ |
| `PBX_PROVISIONING_*` côté NIMBORA : URL privée `https://10.250.0.10` (certificat non vérifié), ARI `http://10.250.0.10:5039`, `ON_SIGNUP=false` | ✅ après 🐛 n° 8 (variables non transmises par compose) |
| Deux entreprises de test créées (inscription ouverte quelques minutes puis refermée), administrateur passé super-admin pour l'API opérateur | ✅ organisations 2 et 3 |
| `GET /pbx/plan` : `shared: true`, `shared_available: true` (hors SaaS, tout est permis) | ✅ |
| `POST /pbx/provision` entreprise A : tenant `org2` (« Entreprise 2 (#org2) »), contextes interne/entrant/sortant, compte `nimbora-org2`, configuration ARI n° 2 « PBX de la plateforme (agents IA) », abonnement webhook, connexion `managed: true`, `status: ok`, moteur 26.11 | ✅ en 1,3 s |
| `POST /pbx/provision` entreprise B : tenant `org3`, même chose, ARI n° 3 | ✅ en 1,2 s |
| Second `POST /pbx/provision` sur chacune : même tenant, même ARI, rien de doublé (idempotence) | ✅ |
| L'entreprise modifie sa connexion gérée (`PUT /pbx/connection`) | ✅ refusé 409 « géré par la plateforme » |
| Isolation côté moteur : jeton du compte de service d'« Entreprise test » sur le tenant `org2` → **401**, sur son propre tenant → 200 (ses 2 postes seulement) ; le compte d'approvisionnement voit les 4 tenants | ✅ |
| Création du poste 1001 dans A puis dans B | ❌ 502 « 409 Conflict … /auth/0.1/users » → 🐛 n° 9 |
| Création d'un numéro public `+2250700000002` dans A | ❌ 502 « exten: String does not match expected pattern » → 🐛 n° 10 (bogue de `main`, pas de la PR) ; sans `+` : ✅ |

### 🐛 n° 8 — `PBX_PROVISIONING_*` (et `BRAND_*`) n'atteignaient pas le conteneur API

Le service `api` de `docker-compose.yaml` liste ses variables une à une : celles du `.env`
qui n'y figurent pas sont ignorées. Aucun `PBX_PROVISIONING_*` n'était transmis, la
plateforme ne « voyait » donc pas de PBX partagé ; les `BRAND_*` de la marque blanche non
plus. Correction : les deux fichiers compose transmettent chaque variable lue par
`api/constants.py` (test qui compare les deux listes), et `branding.py` traite une variable
vide comme absente (compose transmet `${VAR:-}` vide). Commits `32e1456` (main) et
`edc0466` (branche).

### 🐛 n° 9 — identifiants `poste1001` non uniques entre tenants

Les identifiants de connexion (wazo-auth) sont uniques sur **tout le moteur**, pas par
tenant : le `poste1001` d'« Entreprise test » bloque celui de l'entreprise A (409), et le
moteur annule bien la création (aucun utilisateur orphelin). Correction (`admin.py`) : sur
une connexion gérée par la plateforme, l'identifiant par défaut devient `org2-poste1001` ;
un PBX dédié garde `poste1001` ; une adresse e-mail reste l'identifiant. Le faux PBX des
tests refuse désormais un identifiant en double. Test
`test_logins_on_the_shared_pbx_carry_the_tenant_slug`.

### 🐛 n° 10 — le moteur refuse le `+` des numéros publics

`POST /confd/1.1/extensions` avec `exten: "+2250700000002"` → « String does not match
expected pattern », sur le tenant dédié comme sur les tenants partagés : aucun numéro en
+E.164 ne pouvait être créé depuis NIMBORA. Correction (`main`, `service.py` et
`numbers.py`) : le numéro est écrit et comparé **sans son `+`** côté moteur (`pbx_exten`),
NIMBORA et l'argument `called=` de Stasis gardent le +E.164, et l'inventaire retrouve les
numéros confiés à l'IA sous les deux formes. Le faux PBX refuse le `+` comme le moteur.

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

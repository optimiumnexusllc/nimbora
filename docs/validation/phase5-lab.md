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
| Après correctifs (image API reconstruite depuis la branche fusionnée) : poste 1001 dans A **et** dans B, identifiants `org2-poste1001` / `org3-poste1001` ; « Entreprise test » garde `poste1001` et `poste1002` ; chaque tenant ne contient que ses postes (`confd/users` par tenant) | ✅ |
| Inventaire de A : son seul poste 1001 et son numéro ; inventaire de B : idem ; aucun ne voit l'autre | ✅ |
| Numéro public `+2250700000003` dans B après le correctif n° 10 : créé (`2250700000003` sur le moteur), visible seulement dans B | ✅ |
| Kit lab : `--shared-pbx` (moteur `--operator`, compte d'approvisionnement, `PBX_PROVISIONING_*` dans le `.env`) rejoué sur le laboratoire avec `--only nimbora` | ✅ |
| Tests : branche 91 tests PBX/provisioning/SaaS, `main` 89 + kits 22 et 24 ; `test_stream_pushes_changes_on_pbx_events` échoue dans la suite complète et passe seul (connu, antérieur à la PR) | ✅ |

### Reste à valider pour la PR (🧪)

- ACL exactes du compte d'approvisionnement : vérifiées par l'usage réel (tenants, contextes,
  politiques, comptes, inclusion de contextes) ; `auth.users.*.policies.*.create` a fonctionné.
- Agents IA de deux entreprises sur le même Asterisk (deux applications Stasis) : non
  vérifiable sans clé de fournisseur IA.
- Appel humain réel entre deux postes de tenants différents (doit échouer) : à faire lors du
  test humain.
- Les contextes entrants créés par le moteur pour `org2`/`org3` n'ont **aucune plage**
  (`incall_ranges: []`) : la création de numéros fonctionne quand même sur 26.11, à surveiller.
  → **Corrigé** (branche `feat/lot-a-object-storage`) : le moteur crée ces contextes avec le
  tenant ; le provisionnement (et `ensure_tenant_contexts.py`) complète désormais les plages
  vides (entrants 4 à 15 chiffres, postes, groupes, files, conférences) sans toucher aux plages
  déjà définies. À revérifier : `POST /pbx/provision` sur `org2` puis `confd/contexts` du tenant.


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
## Rapport d'étape 7 — vérifications pour les PR #2 et #3 (21 novembre 2026)

**Inscription publique.** Fermée depuis la création du compte administrateur :
`ENABLE_SIGNUP=false`, `/api/v1/health` → `signup_enabled: false`, `POST /auth/signup` → 403.
Elle n'a été rouverte que quelques minutes pour créer les deux entreprises de test, puis
refermée (vérifié après chaque bascule).

**PR #2, connexion et inscription en français.** Interface construite depuis la branche
`feat/auth-fr-signup-control`, lancée dans un conteneur jetable branché sur l'API du
laboratoire (inscription fermée), captures Chromium : `/auth/login` entièrement en français
(« Connexion », « Saisissez votre e-mail et votre mot de passe », « Se connecter ») ;
`/auth/signup` affiche « Inscriptions fermées — Les comptes de cette plateforme sont créés par
son administrateur… » au lieu du formulaire ; un mauvais mot de passe donne « E-mail ou mot de
passe incorrect ». ✅ Captures jointes au rapport de session (non versionnées).

**PR #3, minutes humaines : sens du champ `duration` du journal d'appels du moteur.**
Outil : conteneur Incus jetable `nimbora-siptest` (Debian 12, baresip 1.0) sur le pont privé,
deux clients SIP enregistrés sur les postes 1002 et 1003 (poste 1003 créé pour servir de
répondeur), audio 8 kHz dans les deux sens (RTP établi des deux côtés).

| Appel réel (tenant « Entreprise test », `call-logd/1.0/cdr`) | start → answer | start → end | end → answer | `duration` |
|---|---|---|---|---|
| n° 2 : décroché automatique, raccroché par l'appelant | 0,4 s | 40,0 s | 39,6 s | **39** |
| n° 3 : décroché après 12 s de sonnerie (`/accept` envoyé par `ctrl_tcp`) | 12,1 s | 42,0 s | 29,9 s | **29** |
| n° 1 : jamais décroché (client mal configuré) | `answer: null` | 31,5 s | — | `null`, `answered: false` |

Conclusion ✅ : sur Wazo 26.11, `duration` est le temps **du décroché au raccroché**, en
secondes entières **tronquées** (29,9 → 29), `null` pour un appel non décroché ; la sonnerie
n'est jamais comptée. `billing.py` de la PR #3 lit `duration` et `answered` : c'est le bon
champ. Les appels de test sont `call_direction: internal` et ne sont donc pas facturables, ce
qui est le comportement voulu ; un appel `inbound`/`outbound` réel demande un opérateur (🧪).

**Constat utile pour le test humain.** Le moteur identifie un poste par le **nom du point de
terminaison** (`identify_by = username,ip`, ex. `pqxtdakl`), le « SIP username » rendu par
NIMBORA (`poste7640`) ne servant qu'à l'authentification. Un client SIP générique doit donc
mettre le nom du point de terminaison en identité et le SIP username en identifiant
d'authentification ; mes premiers essais avec le seul SIP username ont été refusés (« No
matching endpoint ») et fail2ban `asterisk-wazo` a banni le conteneur de test après 15
échecs, preuve que cette prison fonctionne. Amélioration proposée : renvoyer aussi le nom du
point de terminaison dans la fiche d'identifiants d'un poste (`ExtensionCredentials`).

## Rapport d'étape 8 — PR #3, #4 et #5 sur le laboratoire (21 novembre 2026)

Branche `feat/lot-a-object-storage` (PR #5, qui contient #1, #3 et #4) fusionnée avec `main`,
images construites (`REGISTRY=nimbora-lot-a5`), déployée par le kit lab ; migrations
`c6d7e8f9a0b1` et `d7e8f9a0b1c2` appliquées (`alembic current` → `d7e8f9a0b1c2 (head)`).

### Sécurité du bucket (PR #5)

| Vérification | Résultat |
|---|---|
| Avant tout : `mc anonymous get local/voice-audio` → `private`, `GET /voice-audio/?list-type=2` via Traefik → **403** | ✅ (déjà privé) |
| Bucket rendu volontairement public (`mc anonymous set download`, listage → 200) puis démarrage de l'API de la PR : politique → `private`, listage → **403** | ✅ l'API retire la politique anonyme au démarrage |
| Lien signé (enregistrement de test déposé par la couche de stockage) à travers Traefik | ✅ 200, 16 044 octets |
| Signature altérée / autre objet avec la même signature / chemin non signé | ✅ 403 / 403 / 403 |
| Lien à 2 s de validité lu après 4 s | ✅ 403 (expiré) |
| Type de contenu du lien « inline » : `application/octet-stream` au lieu de `audio/wav` | 🐛 n° 12, corrigé (`response-content-type` demandé comme sur S3), test unitaire |

### Minutes humaines (PR #3) sur de vrais journaux d'appels

Outils : conteneur `nimbora-siptest` (postes 1002 et 1003) et conteneur `nimbora-operator`
(10.250.0.208) qui joue l'opérateur SIP : ligne opérateur par IP créée depuis NIMBORA,
route sortante `_00.` (2 chiffres retirés), numéro public `2250700000001` vers le poste 1003.
Constat : le moteur identifie les postes par `auth_username,username,ip`, le trunk par IP.

| Vérification | Résultat |
|---|---|
| `duration` = décroché → raccroché (rapport d'étape 7 ; confirmé sur les nouveaux appels : 21 s et 14 s) | ✅ |
| `GET /cdr?from=…&order=start&direction=asc&limit=2&offset=0/2/4` : identifiants 1-2, 3-4, 5-6, `total`/`filtered` = 7, départs croissants | ✅ pagination correcte |
| Appel **sortant** par la ligne opérateur (1003 → 0033123456789, 22 s) : `call_direction: outbound`, `answered: true`, `duration: 21` | ✅ |
| Appel **entrant** de l'opérateur vers le numéro public (→ 1003, 15 s) : `inbound`, `answered: true`, `duration: 14` | ✅ |
| Appel interne 1002 → 1003 (29 s) et appel sortant non décroché | ✅ non facturables (interne / `answered: false`) |
| `sync_human_minutes` : les deux appels externes déjà comptés par le webhook ; deux exécutions → toujours 2 lignes | ✅ aucun doublon |
| Rattrapage : lignes effacées et `usage_synced_at` remis à zéro → `counted: 2` (exactement les deux externes), seconde exécution `counted: 0` | ✅ |
| `GET /api/v1/saas/admin/usage?month=2026-11` : 404 tant que `SAAS_MODE` n'atteint pas le conteneur | 🐛 n° 13, corrigé (compose) |
| Même appel après correction, `SAAS_MODE=true` : organisation 1 `human_minutes: 0.58` (35 s), 1 000 incluses, 0 dépassement ; CSV `;` identique | ✅ (`company_name` vide pour les organisations créées hors SaaS : à renseigner par l'opérateur) |
| Nom saisi à l'inscription (`Awa Koné Test`) renvoyé par `/auth/me` | ✅ (organisation 4 de test créée pour cela, inscription refermée) |
| `test_pbx_groups_conferences.py` (cassé sur `main` par 9969fa0, réparé dans la branche) | ✅ passe dans la suite de la branche |

### Sauvegarde et restauration du PBX (PR #4)

| Vérification | Résultat |
|---|---|
| `scripts/backup.sh` avec `BACKUP_PASSPHRASE_FILE` de test : `pg_dumpall`, archives chiffrées (`.enc`), `SHA256SUMS`, `manifest.json` (moteur `26.11~20261013…`) | ✅ 15,5 Mo |
| Dossiers de Wazo 26.11 présents sur le moteur mais **absents de la liste** : `var/lib/wazo-auth-keys` (identifiants internes des services), `var/lib/asterisk/keys` (DTLS WebRTC), `var/lib/asterisk/astdb.sqlite3`, `var/lib/asterisk/sounds`, `var/spool/asterisk/recording`, états `wazo-call-logd`, `wazo-agentd`, `wazo-chatd`… | 🐛 n° 14, liste complétée (38 chemins sauvegardés), test |
| `restore.sh --check` : intégrité, déchiffrement, archives lisibles, rien d'arrêté | ✅ |
| **Restauration réelle** (`--yes`, instantané Incus pris avant) : moteur arrêté, bases rechargées, fichiers restaurés, redémarrage « Wazo fully booted », 58 s | ✅ |
| Après restauration : 4 tenants, postes/files par tenant identiques (3/1, 1/0, 1/0), 18 services, 8 points de terminaison, pare-feu rechargé | ✅ |

### Prometheus et Grafana (PR #4)

| Vérification | Résultat |
|---|---|
| `install.sh --firewall-only --metrics-from 10.250.0.1` sur le PBX | 🐛 n° 15 : ouvrait 9100 sans installer l'exporteur ; corrigé, exporteur actif (1 405 séries) |
| Exporteur de l'hôte, lié à la passerelle Docker `10.0.0.1:9100` seulement (3 400 séries) | ✅ |
| `deploy/observability` : secret devops `chmod 600` illisible par Prometheus (`nobody`) → toutes les cibles `nimbora` « unable to read headers file » | 🐛 n° 16 : documentation et commentaire corrigés (`644`, dossier privé), test |
| Prometheus relié au réseau de la pile avec `gw_priority` pour joindre le PBX par le pont connu du pare-feu | ✅ |
| Cibles : `nimbora` ×2 workers, `nimbora-business`, `node` PBX et hôte → **5/5 up** ; 3 groupes, **11 alertes** chargées | ✅ |
| Grafana 12 : dossier NIMBORA et tableau « NIMBORA operations » provisionnés ; capture prise (locale du navigateur requise, sinon « failed to load its application files ») | ✅ |
| Kit lab : nouvelle phase `--observability` qui reproduit tout cela, test | ✅ |
| Métrique de fraîcheur de la sauvegarde (`nimbora_pbx_backup_last_success_timestamp_seconds`) : absente de Prometheus, tableau « Dernière sauvegarde du PBX » à « No data » | 🐛 n° 17 : l'exporteur Debian démarre avec `ARGS=""` sans répertoire textfile → le kit le règle ; 🐛 n° 18 : fichier `.prom` écrit en `600` (umask du script) illisible par l'utilisateur `prometheus` → `644`. Après correction : métrique vue par Prometheus pour `10.250.0.10:9100` ; tests |

Après la validation : `SAAS_MODE=true` reste actif sur le laboratoire (abonnements « Starter »
en essai créés pour les 4 organisations).

## Rapport d'étape 9 — plages des contextes (PR #5, `358fb93`) et routage intelligent (PR #6) (22 novembre 2026)

Déployé : pointe de `feat/lot-b-smart-routing` (rebasée sur `feat/lot-a-object-storage` à
`358fb93`), images `nimbora-lot-b`, pas de nouvelle migration (tête `d7e8f9a0b1c2`).

### Préalable découvert : `SAAS_MODE` et le PBX privé

Depuis le passage en `SAAS_MODE=true` (étape 8), la garde anti-SSRF refusait l'adresse privée du
PBX (`https://10.250.0.10`) : approvisionnement, inventaire et lignes opérateurs répondaient 502
« pas joignable publiquement ». `PBX_ALLOWED_HOSTS` existait mais n'était pas transmis par
compose. Correction sur la PR #5 (`9b789dd`) : variable transmise, et le kit lab la règle sur
l'adresse du PBX avec `--shared-pbx` ; tests.

### 1. Plages des contextes créés par le moteur (PR #5, commit `358fb93`)

| Vérification | Résultat |
|---|---|
| Premier `POST /pbx/provision` org2 et org3 après redéploiement | ❌ 502 « accès refusé (`confd.contexts.5.update`) » → 🐛 n° 19 |
| 🐛 n° 19 : le nouveau `PUT /contexts/{id}` n'était pas couvert par la politique d'approvisionnement | corrigé (`2c18595`) : `confd.contexts.*.update` dans `PROVISIONING_ACL` et `provisioning-policy.json` (test existant maintenu en phase), politique rejouée sur le moteur (122 ACL) |
| `POST /pbx/provision` org2 et org3 après correction | ✅ 200, mêmes tenants, mêmes contextes |
| `confd/contexts` de chaque tenant : contexte entrant `incall_ranges` **12 plages de 4 à 15 chiffres**, `did_length` = longueur | ✅ |
| Plages existantes du contexte interne inchangées (postes 1000-1999, groupes 2000-2099, files 3000-3099, conférences 4000-4099 posées à la création) | ✅ conservées telles quelles |
| Aucun contexte en double : 3 contextes, 3 noms distincts par tenant ; inclusion interne → sortant intacte | ✅ |
| Numéro public `+2250700000022` créé dans org2 (vers son poste 1001) ; ligne opérateur par IP dans org2 ; appel depuis `nimbora-operator` (identité `33987654321`) | ✅ l'appel entre dans `ctx-org2-incall-…`, sonne « Agent A 1001 » (poste non enregistré, donc non décroché), journal d'appels d'org2 : `inbound` |

### 2. Routage intelligent (PR #6)

| Étape demandée | Résultat |
|---|---|
| Onglet **PBX → Routage** dans la console (connexion administrateur, Chromium) | ✅ onglet présent entre « Enregistrements » et « Journal », bloc politique et simulateur rendus (capture prise) |
| Deux compétences : « Facturation » → file `pbx-queue:1` (Support test), « Technique » sans destination ; postes 1001 (Facturation, `fr`) et 1002 (Facturation + Technique, `fr, en`) ; `PUT /pbx/routing` | ✅ enregistrée et relue à l'identique |
| (a) agent 1001 connecté à la file (`login`, contexte interne), libre → simulation « Facturation » | ✅ `pbx-queue:1`, motif `skill` |
| (b) agent 1001 en pause → « Facturation » | ✅ `pbx-extension:1002`, motif `skill_agent` (« poste 1002 libre ») ; idem avec langue `en` (1001 ne parle que `fr`) |
| (c) appel 1003 → 1002 en cours (vu dans l'état en direct) → « Technique » | ✅ `destination: null`, motif `unavailable`, étapes « Pas de conseiller habituel connu », « Personne de libre pour « Technique » » ; « Facturation » pendant l'appel → la file (agent 1001 libre) ; après raccroché → 1002 à nouveau |
| (4) vrai appel entrant de 40 s depuis `nimbora-operator` (`33123456789`, client connu `+33123456789`, 3 appels déjà) décroché par le poste 1003 | ❌ au premier essai : webhook `call_log_created` reçu, compteur d'appels 3 → 4, mais `attributes.usual_advisor` absent → 🐛 n° 20 |
| 🐛 n° 20 : pour un appel entrant le code lisait `destination_extension`, qui est le **numéro public** composé (`2250700000001`, 13 chiffres, refusé par `remember_advisor`) ; le poste de l'employé est `destination_internal_extension` (`1003`) — même chose côté source pour les sortants | corrigé (`5115ee9`) sur la PR #6, test avec la forme réelle du journal d'appels (entrant et sortant) |
| Après correction, nouvel appel de 40 s : `attributes.usual_advisor = {extension: 1003, name: Test 1003…, at: …}` | ✅ |
| Simulateur avec `caller_number +33123456789` | ✅ `pbx-extension:1003`, motif `usual_advisor`, « Conseiller habituel disponible : Test 1003 (SIP, répondeur automatique) », quelle que soit la compétence demandée |
| Même simulation pendant que 1003 est en appel | ✅ « Conseiller habituel (…) indisponible » puis `pbx-queue:1` par la compétence |
| `grep "Routing"` dans les journaux de l'API | aucune ligne : le simulateur ne journalise pas ; la ligne `[Routing org=…]` n'existe que sur la passation réelle (`resolve_for_transfer`), impossible à exercer sans clé IA. Amélioration proposée : journaliser aussi les décisions du simulateur |

Écarts restants : dans le journal de l'API, une trentaine de traces `httpx.ConnectError:
Name or service not known` vers `agentd`, `amid` et `auth` du PBX (hôte masqué par la
rédaction des journaux), non reproduites pendant les tests ; à dater et expliquer.

## Rapport d'étape 10 — présence des collègues et annuaire unifié (PR #7) (22 novembre 2026)

Déployé : `feat/lot-b-presence-directory` (images `nimbora-lot-b7`), d'abord `fa6dbee` fusionnée
avec `feat/lot-b-smart-routing` (`b948fa8`), puis la branche telle que réécrite par son auteur
sur `c3bbc7d` (`8fdfa79`) ; les deux correctifs ci-dessous ont été rejoués dessus. Aucune nouvelle
migration. Le Softphone web (`softphone/`, version 1.2.0) a été construit depuis la branche et
servi en local, appairé au poste 1004. Sans fusion.

### Préalable : postes appairables

Les postes 1002 et 1003 sont des lignes SIP classiques : l'appairage répond 409 « pas de ligne
navigateur », comme prévu. Les essais ont donc utilisé 1001 (ligne navigateur) et un nouveau
poste navigateur 1004, créé après avoir porté le plafond de sièges humains du tenant 1 à 10
(`PATCH /saas/admin/tenants/1`, `limit_overrides.max_human_seats`).

| Étape demandée | Résultat |
|---|---|
| (2) **avant** la mise à jour des droits : `GET /softphone/directory` avec le jeton du poste 1004 | `presence_live: true` dès le départ : wazo-chatd 26.11 **ne fait pas respecter** `chatd.users.presences.read` (la politique à 110 ACL lisait déjà les présences). Le repli `presence_live: false` n'est donc pas observable sur ce moteur ; il reste couvert par les tests unitaires. Pendant un appel 1002 → 1003, les deux postes sont bien « En appel » |
| (3) `create_service_account.py --provisioner` puis `POST /pbx/provision` org2 | ✅ compte opérateur **125 ACL** (112 + 13 : la PR #5 a ajouté `confd.contexts.*.update`, d'où 13 et non 12), compte dédié 112 ; la politique du tenant org2 contient `chatd.users.presences.read` (et `update`). org3 non réapprovisionné (politique à 110) |
| (4) `GET /api/chatd/1.0/users/presences` avec le compte de service | ✅ forme : `items[] = {uuid, tenant_uuid, state (available/away/unavailable/invisible), status, line_state (available/unavailable/talking/ringing/holding), do_not_disturb, connected, mobile, last_activity, lines[{id, state}]}` |
| (5) appel en cours entre deux postes | ✅ « En appel » sur 1002 et 1003 (API et console) |
| (5) « Ne pas déranger » posé sur 1002 (`PUT /pbx/extensions/{id}/call-settings`) | ✅ « Ne pas déranger » (API, console, Softphone) |
| (5) `PUT /api/v1/softphone/presence {"state":"away","status":"Déjeuner"}` depuis le poste 1001 | ✅ « Absent · Déjeuner » dans **PBX → Postes** (capture Chromium) et dans le **Softphone web** (liste Collègues : « Absent · Déjeuner / Ne pas déranger / Disponible ») |
| (5) poste sans téléphone enregistré (1004 avant appairage) | ✅ « Hors ligne » |
| (6) mémoire client activée : `GET /softphone/directory?q=Awa` et `?q=<fin du numéro>` | ✅ `customers: [Awa Koné (test), conseiller habituel Test 1003, 5 appels]` |
| (6) mémoire client désactivée | ✅ `customers: null` (puis réactivée) |

Bugs trouvés et corrigés sur la branche :

| N° | Symptôme | Cause | Correction |
|---|---|---|---|
| 21 | Postes 1002 et 1003 enregistrés et libres affichés « Hors ligne » | sur le moteur, un utilisateur qui n'a jamais choisi de présence reste `state: unavailable` pour toujours, téléphone enregistré ou non ; le code traduisait `unavailable` en hors ligne sans regarder la ligne | `603b00d` : la ligne décide (`line_state: available` → disponible ; rien d'enregistré, pas d'application, pas de mobile → hors ligne) ; tests avec les formes vues sur le moteur |
| 22 | Softphone web : « Identifiants SIP refusés par le PBX », `Failed to authenticate` dans les journaux Asterisk alors que le mot de passe servi par l'API est le bon | le moteur identifie le point de terminaison par l'utilisateur SIP de la requête (`identify_by = username`, c'est-à-dire le **nom du point de terminaison**) ; le nom d'authentification (`poste####`) ne sert qu'au défi ; le Softphone s'enregistrait en `sip:<nom d'authentification>@…` | `22c2290` : la configuration du poste porte `sip_identity` (nom du point de terminaison) ; l'application s'enregistre avec et passe le nom d'authentification en `authorization_user` (même réglage que la procédure Linphone du laboratoire). Après correction : Softphone « Disponible », plus aucun échec d'authentification côté moteur. Tests API et Vitest |

Autres observations :

- Un fichier `dump.rdb` (vidage Redis) était versionné dans la PR : retiré et ajouté à `.gitignore` (`22c2290`).
- Le commit `c3bbc7d` de la PR #6 journalise désormais les décisions du simulateur : ligne
  `[Routing org=1 simulation] skill → pbx-queue:1 | …` observée dans les journaux de l'API
  (suite de la remarque de l'étape 9).
- Le « Hors ligne » d'un poste navigateur dont l'application est fermée est normal : JsSIP se
  désenregistre à la fermeture.
- Écart de l'étape 9 daté : les traces `httpx.ConnectError: Name or service not known` viennent
  de l'**amorçage d'organisation** (`organization_bootstrap.py`, « Failed to bootstrap
  organization 1; will retry on a later request »), qui tente de créer un compte de facturation
  hébergé sur `MPS_API_URL` (valeur par défaut `https://services.nimbora.example`, hôte
  inexistant) et recommence à chaque requête. Sans rapport avec le PBX ni avec les PR validées ;
  à neutraliser dans le kit (variable vide ou amorçage hébergé désactivé en auto-hébergement).
  → **Corrigé** (branche `feat/lot-b-presence-directory`) : l'adresse par défaut est un exemple ;
  avec elle (ou vide, ou `off`), les services hébergés sont coupés, l'amorçage ne contacte plus
  rien et se termine (l'entreprise apporte ses clés IA). À revérifier : plus aucune trace
  `Name or service not known` après redéploiement.

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

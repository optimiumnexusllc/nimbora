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

### Écart `ConnectError` de l'étape 9 : expliqué (sans rapport avec le PBX)

| Vérification | Résultat |
|---|---|
| (a) `pbx_connections` : `organization_id, managed, hôte` | `1 / f / 10.250.0.10`, `2 / t / 10.250.0.10`, `3 / t / 10.250.0.10` ; `PBX_PROVISIONING_URL` : hôte `10.250.0.10`. **Aucun nom d'hôte**, uniquement l'adresse privée du moteur, résolue à l'identique depuis le conteneur API (`getent hosts`) |
| (b) dates | conteneur API courant démarré à 09:41:46 UTC (pointe réécrite de la PR #7) ; les deux lignes `Name or service not known` (une exception `httpcore` chaînée en `httpx`) sont à **09:42:34**, soit la première requête authentifiée après le redémarrage. Les journaux des conteneurs précédents ont disparu avec eux (`docker events` ne conserve pas les `start` sur 24 h) ; la trentaine de traces de l'étape 9 correspondait au même motif, une fois par bail d'amorçage |
| (c) pile (fichiers NIMBORA) | `routes/public_embed.py:277 __call__` → `services/auth/depends.py:44 get_user` → `depends.py:321 _handle_oss_auth` → **`services/organization_bootstrap.py:100 ensure_organization_bootstrapped`** → `organization_bootstrap.py:183 _bootstrap_organization` → `organization_bootstrap.py:214 mint_managed_service_key` → `services/mps_service_key_client.py:226 create_service_key` → `httpx` → DNS. Message journalisé : « Failed to bootstrap organization 1; will retry on a later request » |
| cause | l'organisation 1 n'a **aucune configuration de modèle** (pas de clé d'IA sur ce laboratoire) : l'amorçage tente alors de créer une clé de service hébergée sur `MPS_API_URL`, dont la valeur par défaut `https://services.nimbora.example` ne se résout pas. Rien à voir avec `agentd`, `amid` ou `auth` du PBX |
| (d) libellé des erreurs PBX après `c3bbc7d` | non déclenchable ici (le PBX n'est joint que par adresse IP) ; le libellé « PBX injoignable (service) : ConnectError (nom d'hôte du PBX non résolu) » est couvert par `test_pbx.py` (cas `auth`) ; aucune erreur PBX dans les journaux depuis le redéploiement |

Correction de l'auteur (`fb9acfc`) : `MPS_ENABLED` est faux quand `MPS_API_URL` est vide, `off`
ou un hôte `.example` ; l'amorçage se termine alors sans contacter de service hébergé.
Revérifié après redéploiement de `fb9acfc` (API démarrée à 10:17:27 UTC, `MPS_API_URL` non
défini sur le laboratoire) : requêtes authentifiées (profil, inventaire, routage, clients,
présence), journal : **0** `Name or service not known`, **0** « Failed to bootstrap », une ligne
« Organization 1 bootstrapped without hosted services (MPS off) ». ✅ Les tests
`test_organization_bootstrap.py` passent (78 tests sur les cinq fichiers concernés).
Avec le même commit, « Hors ligne » choisi depuis le Softphone est envoyé en `invisible` :
`PUT /softphone/presence {"state":"offline"}` sur 1001 → « Hors ligne » vu du poste 1004, puis
retour « Disponible » ✅.

### Journal du routage (PR #6, `c3bbc7d`)

| Simulation | Ligne journalisée |
|---|---|
| `{"skill": "Facturation", "caller_number": <numéro de la cliente de test>}` | `[Routing org=1 simulation] usual_advisor → pbx-extension:1003 \| → Conseiller habituel disponible : Test 1003 (SIP, répondeur automatique)` |
| `{"skill": "Technique"}` pendant un appel 1003 → 1002 (seul expert occupé) | `[Routing org=1 simulation] unavailable/queue → — \| Pas de conseiller habituel connu ; Personne de libre pour « Technique »` |

Le numéro du client n'apparaît dans aucune de ces lignes (vérifié par `grep`).

## Rapport d'étape 11 — « Hors ligne » choisi, services hébergés coupés, rotation des secrets SIP (22 novembre 2026)

Déployé : `feat/lot-b-presence-directory` à `a5878bc` (`fb9acfc` inclus), image `nimbora-lot-b7`,
API redémarrée à 10:17:27 UTC. Softphone web construit depuis la branche (1.2.0), appairé au
poste 1004. Sans fusion.

### 1. « Hors ligne » choisi dans le Softphone (envoyé en `invisible`)

| Étape | Résultat |
|---|---|
| Softphone web 1004 ouvert (Chromium) : enregistrement | ✅ « Disponible » à 10:27:28 |
| Réglages → Ma présence → **Hors ligne** (bouton `aria-pressed`) | ✅ pris en compte à 10:27:32 ; l'indicateur d'enregistrement reste « Disponible » |
| Vu depuis le poste 1001 (`GET /softphone/directory` avec son jeton) | ✅ 1004 : « Hors ligne », `state: offline` |
| Moteur : `pjsip show contacts` pendant la fenêtre | ✅ contact de l'endpoint du poste 1004 présent (téléphone **toujours enregistré**) |
| Console PBX → Postes (Chromium, pendant la fenêtre) | ✅ 1004 « Hors ligne » (1001 « Hors ligne » car non enregistré, 1002 et 1003 « Disponible ») |
| Après 70 s, Réglages → **Disponible** | ✅ « Disponible » à 10:28:46, téléphone resté enregistré pendant toute la séquence |

### 2. Services hébergés coupés (`MPS_API_URL` à sa valeur d'exemple)

`MPS_API_URL` n'est pas défini sur le laboratoire : la valeur par défaut (hôte `.example`) coupe
les services hébergés (`MPS_ENABLED` faux).

| Vérification | Résultat |
|---|---|
| 15 minutes d'usage (10:25:54 → 10:41:35 UTC) : boucle de 12 requêtes toutes les 25 s sur les trois organisations (profil, inventaire, routage, supervision, clients, journal d'appels, annuaire et configuration Softphone), plus sessions Chromium de la console (PBX → Postes, Routage) et du Softphone 1004 | 420 requêtes de la boucle, toutes en 200 ; 2 041 requêtes HTTP journalisées par l'API sur la fenêtre |
| `docker logs --since 15m nimbora_api \| grep -c "Name or service not known"` | ✅ **0** (0 aussi depuis le démarrage de l'API) |
| `grep -c "Failed to bootstrap organization"` sur la même fenêtre | ✅ **0** |
| « bootstrapped without hosted services (MPS off) » | ✅ **une ligne par organisation** : 1, 2 et 3 |


### 3. Rotation des mots de passe SIP de 1001 et 1004

✅ **Faite par l'opérateur, via script** (`/home/messie/nimbora-lab-rotate-sip.sh`, hors dépôt), après
trois constats :

- La console n'offre pas de régénération du mot de passe SIP : le bouton « Mot de passe » d'un
  poste envoie un lien de réinitialisation du **mot de passe de connexion**
  (`POST /pbx/extensions/password-reset`), et le secret SIP n'est montré qu'à la création.
- Le compte de service NIMBORA ne peut pas le faire : sa politique contient
  `confd.endpoints.sip.*.read`, `create` et `delete`, mais ni `confd.endpoints.sip.read` (liste)
  ni `confd.endpoints.sip.*.update` (jeton à 174 ACL ; `GET /endpoints/sip?name=…` → 401).
- La session d'assistance n'a pas été autorisée à utiliser le compte d'administration du moteur.

Le script, lancé par l'opérateur sur l'hôte, entre dans le conteneur du PBX, prend un jeton
d'administration (`wazo-auth-cli`), remplace le mot de passe de l'endpoint de chaque poste
(`PUT /confd/1.1/endpoints/sip/{uuid}`), relit pour vérifier, et écrit les nouvelles valeurs
dans le fichier local des postes (mode 600). Empreintes SHA-256 (12 premiers caractères) :
1001 `db853d7ad1e1`, 1004 `b892615173ed` ; moteur et fichier **identiques** à la vérification.
Aucun client SIP de test n'utilisait 1001 (les clients `baresip` du laboratoire sont 1002, 1003
et les lignes opérateurs) : rien à reconfigurer. Le Softphone web 1004 est revérifié à l'étape 12.

Une action « Régénérer le mot de passe SIP » dans la console est annoncée pour une prochaine PR.

## Rapport d'étape 12 — redéploiement depuis `main`, puis PR #9 « Régénérer le mot de passe SIP » (22 novembre 2026)

### A. Laboratoire redéployé depuis `main`

Déployé : `main` à `61932c8` (PR #1 à #7 et #2 fusionnées, CI verte), même procédure que pour
la PR #7 : images `nimbora-main` (API, UI) construites depuis le dépôt, kit lab
`deploy/lab/install.sh --only nimbora --no-build`, migrations à jour (tête `d7e8f9a0b1c2`,
aucune nouvelle). Softphone web 1.2.0 construit depuis `main`. Les anciennes branches ne sont
plus touchées ; ce rapport est consigné sur la branche de la PR #9.

#### 1. Vérifications après redéploiement

| Vérification | Résultat |
|---|---|
| `GET /api/v1/health` derrière Traefik | ✅ 200, `status: ok`, version 1.51.0 |
| Conteneurs `nimbora_api` et `nimbora_ui` (images `nimbora-main/…`) | ✅ `healthy` |
| Console → PBX → **Routage** (Chromium, administrateur) | ✅ onglet présent, politique et simulateur rendus |
| Console → PBX → **Postes** (présence) | ✅ 1001 « Hors ligne » (poste navigateur sans application ouverte), 1002 et 1003 « Disponible » (SIP enregistrés), 1004 « Hors ligne » |
| Softphone web 1004 (build `main`) avec le **secret SIP régénéré** par l'opérateur | ✅ « Disponible » sans rejumelage (la configuration est relue en direct), contact de l'endpoint présent sur le moteur, aucun nouvel échec d'authentification Asterisk pour ce poste (compteur inchangé) ; Réglages → Hors ligne → Disponible à nouveau OK |
| Journaux de l'API sur 10 minutes d'usage (12:41 → 12:52 UTC, API redémarrée à 12:40:10) : boucle de requêtes toutes les 25 s sur les trois organisations + sessions Chromium console et Softphone | ✅ 87 requêtes de la boucle (toutes 200), 558 requêtes HTTP journalisées sur 12 min ; **0** « Name or service not known », **0** « Failed to bootstrap organization » (0 aussi depuis le démarrage) |

#### 2. Contrôle de non-régression

| Contrôle | Résultat |
|---|---|
| Simulation de routage « Facturation » avec le numéro de la cliente de test | ✅ `pbx-extension:1003`, motif `usual_advisor` ; ligne `[Routing org=1 simulation] usual_advisor → pbx-extension:1003 \| …` journalisée, sans le numéro |
| `GET /saas/admin/usage?month=2026-11` | ✅ 200 : une ligne par organisation facturable (plan `starter`, minutes IA 0, minutes humaines 1,87 incluses dans 1000, devise `eur`) |
| Liste anonyme du bucket : `GET https://app.optimiumnexus.com/voice-audio/?list-type=2` | ✅ **403** |
| Sauvegarde du PBX : `scripts/backup.sh` (chiffrée, phrase secrète dans `/etc/nimbora-pbx/backup-passphrase`, 600) puis `restore.sh --check` sur `/var/backups/nimbora-pbx/20261122-123316` | ✅ 15 Mo, `SHA256SUMS`, `manifest.json` (moteur 26.11), « archives readable: 422 files », « check only: nothing restored ». Le répertoire de sauvegarde était vide avant (les essais de l'étape 8 n'avaient pas été conservés) : **aucune sauvegarde planifiée** sur le laboratoire, à ajouter (minuteur systemd) |

### B. PR #9 — « Régénérer le mot de passe SIP » (`feat/pbx-sip-password-rotation`, base `docs/readme-after-merges`)

Déployé : `fd41032`, images `nimbora-pr9` (API, UI), kit lab `--only nimbora --no-build`,
Softphone web **1.2.1** construit depuis la branche (23 tests Vitest). Tests API de la branche
dans le conteneur : 60 passés (`test_pbx_admin.py`, softphone, approvisionnement, PBX). Sans fusion.

| Étape demandée | Résultat |
|---|---|
| (2) `create_service_account.py --provisioner` relancé dans `nimbora-pbx` (politiques de la PR poussées avant) | ✅ compte opérateur **126 ACL** (125 + `confd.endpoints.sip.*.update`) |
| (2) compte dédié d'org1 (« Entreprise test ») relancé | ✅ politique `nimbora-integration` **113 ACL**, `confd.endpoints.sip.*.update` présent |
| (2) `POST /pbx/provision` org2 | ✅ 200, même tenant ; sa politique relue sur le moteur : 113 ACL, `confd.endpoints.sip.*.update` et `chatd.users.presences.read` présents |
| (3) Softphone web 1004 ouvert avant la rotation | ✅ « Disponible » à 12:53:42, contact présent sur le moteur |
| (3) Console → PBX → Postes → **SIP** sur 1004 (confirmation acceptée) | ✅ dialogue « Nouveau mot de passe SIP · Poste 1004 (…) » avec extension `1004`, identité SIP `v0sleb29`, utilisateur `poste2760`, secret de 20 caractères — **SHA-256 `e69216e167c5…`** (12 premiers caractères). Fermé par « J'ai noté le mot de passe » : zone disparue ; après rechargement de la page, le secret n'apparaît nulle part (affiché une seule fois) |
| (4) Moteur, avant/après (sans le secret) | ✅ **identiques** : endpoint `v0sleb29`, modèles confd `webrtc` + `global`, transport (vue Asterisk `transport-udp`, `webrtc: yes`), `identify_by username,ip`, AOR, auth, contexte, utilisateur `poste2760` ; seule l'empreinte du secret change (`b892615173ed` → `e69216e167c5`) |
| (4) `GET /softphone/config` (jeton du poste 1004) | ✅ même identité et même utilisateur, empreinte `e69216e167c5` : l'API sert le nouveau secret sans rien stocker |
| (5) Ré-inscription spontanée du Softphone (page non rechargée, secret changé à 12:54:17) | ✅ à **13:02:17**, soit **8 min 00 s** après la rotation, au renouvellement périodique de l'enregistrement (expiration 600 s) : le moteur refuse le REGISTER porté par l'ancien secret (une seule notice), l'application relit `/softphone/config` (HTTP 200 à 13:02:17.79) et repart avec le nouveau ; dans le journal Asterisk l'ancien contact WebSocket est retiré et le nouveau ajouté 250 ms plus tard. L'indicateur est resté « Disponible » d'un bout à l'autre (observation toutes les secondes) |
| (5) Aucun rejumelage demandé, pas de boucle d'échecs | ✅ appairage conservé (aucun appel à `/softphone/activate`, jeton inchangé) ; compteur « Failed to authenticate » de ce poste inchangé dans `messages`, une notice unique dans `full` ; fail2ban `asterisk-wazo` : 0 banni |
| (6) `nimbora-lab-postes.txt`, bloc 1004 | ✅ ligne « SIP password » remplacée par le script Chromium (sans affichage), fichier en 600, empreinte `e69216e167c5` identique à celle du moteur |

## Rapport d'étape 14 — PR #10 « transfert avec consultation et conférence à trois » (Softphone 1.3.0) (22 novembre 2026)

Déployé : `feat/lot-b-attended-transfer` à `d760c76` (base `feat/pbx-sip-password-rotation`).
Softphone web **1.3.0** construit depuis `softphone/` (35 tests Vitest, puis 36 avec le correctif
ci-dessous) et servi en local, appairé au poste 1004 dans Chromium sans tête (micro factice,
clics pilotés, états lus toutes les 500 ms). API et UI : images de la PR #9, puis l'API de la
branche (`nimbora-pr10`) après le correctif n° 23. Sans fusion.

Trois parties : **client** = `nimbora-operator` (baresip, identité `33123456789`) appelant le numéro
public `2250700000001`, pointé pour l'essai sur le poste 1004 (remis sur 1003 ensuite) ;
**employé** = 1004 (Softphone web) ; **collègue** = 1002 (baresip dans `nimbora-siptest`, décroche
sur commande). Les observations côté moteur viennent de `core show channels`, `bridge show all`,
`pjsip show channelstats` (paquets RTP par jambe) et du journal `full` (musique d'attente, pile
SIP avec `pjsip set logger on`).

### Préalable : aucun appel n'atteignait une ligne navigateur (🐛 n° 23, préexistant)

| Constat | Détail |
|---|---|
| Premier appel client vers 1004 (enregistré, « Disponible ») | ❌ `Dial(PJSIP/v0sleb29/sip:…;transport=ws)` → « Everyone is busy/congested (1:0/1/0) » **sans aucune trame SIP émise** ; même chose pour 1002 → 1004 |
| Cause (pjproject niveau 5) | « Unsuitable transport selected to reach destination » : l'endpoint avait `transport = transport-udp` alors que son contact est WebSocket. Les modèles du moteur sont corrects (`webrtc` → `transport-wss`, `global` → `transport-udp`) mais NIMBORA posait **[webrtc, global]** sur les lignes navigateur : `global` arrive en dernier et impose `transport-udp` |
| Preuve | endpoint de 1004 remis sur le seul modèle `webrtc` (qui hérite déjà de `global`) → `transport-wss`, et 1004 sonne |
| Correction (branche de la PR #10) | `admin.py::_templates_for` : ligne navigateur → `[webrtc]` seul, ligne SIP → `[global]` ; test `test_pbx_admin.py` ajusté. API reconstruite et déployée : un poste navigateur de contrôle (1005, supprimé ensuite) sort avec `transport-wss` |
| Réparation du laboratoire | endpoints de 1001 et 1004 repassés sur `[webrtc]` (confd, compte de service). **Les installations existantes ont le même défaut sur toutes leurs lignes navigateur** : prévoir une réparation (à l'approvisionnement ou au démarrage de l'API) |
| → Corrigé (`2808b03`, même branche) | chaque Softphone répare sa ligne en lisant son compte ; **Postes → Softphones → Vérifier les lignes navigateur** répare toutes les lignes de l'entreprise (`POST /pbx/maintenance/webrtc-lines`, idempotent). À revérifier : remettre 1004 sur `[webrtc, global]`, ouvrir le Softphone → `[webrtc]` seul et 1004 sonne |

### 1-4. Consultation, bascules, transfert assisté

| Étape | Résultat |
|---|---|
| Appel client → 1004, « Décrocher » | ✅ pont client ↔ 1004, RTP dans les deux sens (ulaw ↔ opus) |
| Transférer → « Collègues disponibles » liste 1002 et 1003 (présence) → 1002 → **Appeler d'abord** | ✅ client mis en attente : « Started music on hold … on channel PJSIP/trunk-… » ; 1002 sonne (canal `Ringing`), Softphone « En attente · … / 1002 Ça sonne… » |
| 1002 décroche, **Basculer** ×2 | ✅ bascule 1 : musique d'attente démarre sur 1002 et s'arrête sur le client ; bascule 2 : l'inverse. Les compteurs RTP émis par 1004 n'avancent que sur la jambe active (l'autre reste figée) : l'audio part du bon côté à chaque fois |
| **Transférer** (REFER avec Replaces) | ✅ « Appel transféré » ; sur le moteur le client est **échangé** dans le pont du collègue : un seul pont client ↔ 1002, RTP qui continue, 1004 sans canal. Aucun REFER refusé (202, NOTIFY 100 puis 200 OK) |
| Journal des appels (console) | ✅ l'appel entrant (destination « Poste 1004 », répondu, durée jusqu'au raccroché final) et l'appel interne 1004 → 1002 de la consultation ; la passation au collègue n'y apparaît pas comme telle (limite de la vue actuelle) |

### 5. Conférence à trois

| Étape | Résultat |
|---|---|
| Nouvel appel, consultation, **Conférence** | ✅ Softphone « Conférence à trois » ; musique d'attente arrêtée ; le moteur voit **deux ponts à deux** (client ↔ 1004a, 1002 ↔ 1004b), le mixage est fait dans l'application (WebAudio) ; les deux jambes de 1004 émettent en continu |
| **Micro coupé** sur 1004 | ✅ pris en compte sur les deux jambes (le mixeur remplace la piste micro pour les deux appels) ; non vérifiable à l'oreille sans tête : les deux jambes continuent d'émettre (voix de l'autre partie) |
| **Se retirer** | ✅ REFER avec Replaces : client et 1002 restent ensemble dans un seul pont, 1004 libéré |
| **Tout raccrocher** (après une nouvelle conférence) | ✅ les trois jambes tombent en même temps : le client (opérateur) et 1002 journalisent « terminated » |

### 6. Cas limites

| Cas | Résultat |
|---|---|
| Transférer pendant que 1002 sonne encore | ✅ la consultation est annulée, REFER simple vers 1002 : le PBX rappelle 1002 pour le client (nouveau canal `Ringing`), 1004 libéré aussitôt ; 1002 décroche → client ↔ 1002 |
| Le client raccroche pendant la consultation | ✅ l'appel avec 1002 continue (pont 1002 ↔ 1004 toujours actif, Softphone « appel en cours »), puis raccroché normal |

### 🐛 n° 24 — après le transfert, 1004 restait « en appel » jusqu'au BYE du PBX (corrigé)

Après un REFER accepté, le moteur raccroche la jambe remplacée immédiatement mais la jambe
principale de l'employé **8 s plus tard** (observé deux fois ; 60 s une fois) : pendant ce temps
le Softphone montrait un appel actif « Appel transféré » et répondait **486 Occupé** aux nouveaux
appels (« Everyone is busy (1:1/0/0) »). Correction dans `phone.ts` : dès le NOTIFY 200 OK
(`accepted`), l'application raccroche elle-même ses deux jambes (RFC 5589), sans reprendre le
client ni promouvoir le collègue entre les deux (sinon un ré-INVITE partait sur un dialogue
déjà clos : « Invalid status: 8 » dans la page) ; test Vitest ajouté.
Revérifié : transfert → « Appel terminé » en moins d'une seconde, un appel 1002 → 1004 lancé 6 s
après sonne et se décroche ; « Se retirer » → idem, client et 1002 restent ensemble ; aucune
erreur de page sur les deux derniers passages.

Observation mineure : après le transfert « 1002 sonne encore », le moteur retransmet pendant
~30 s un `200 OK` (ré-INVITE d'attente dont l'ACK n'est pas parti avant la fin du dialogue) ;
sans effet sur les appels.

### 14 bis — réparation automatique des lignes navigateur (`2808b03`) (22 novembre 2026)

Déployé : pointe `5d69d8c` de `feat/lot-b-attended-transfer`, images `nimbora-pr10` reconstruites
(API et UI), kit lab `--only nimbora --no-build`, `/api/v1/health` 200. État de référence relevé
avant les essais pour les quatre postes (nom d'endpoint, modèles confd, transport vu par
Asterisk, utilisateur d'authentification, empreinte SHA-256 du secret).

| Étape | Résultat |
|---|---|
| (2) Endpoint de 1004 remis à la main sur `[webrtc, global]` (confd, compte de service) | ✅ confd relit `['webrtc', 'global']`, secret et utilisateur inchangés |
| (2) Softphone web 1004 ouvert (il relit `/softphone/config`) | ✅ journal de l'API : `Softphone: browser line v0sleb29 repaired (webrtc template alone)` ; confd : modèles `['webrtc']`, Asterisk : `transport-wss` |
| (2) Appel 1002 → 1004 | ✅ 1004 sonne (canal `Ringing`) et décroche, pont établi |
| (3) Endpoint de 1001 remis sur `[webrtc, global]`, puis Console → Postes → Softphones (bloc « Connexion des softphones au PBX ») → **Vérifier les lignes navigateur** | ✅ toast « **Lignes navigateur réparées : 1001** » ; journal : `[PBX org=1] browser lines repaired: 1001` ; `POST /pbx/maintenance/webrtc-lines` 200 |
| (3) Second clic | ✅ « **4 lignes vérifiées : rien à réparer** » |
| (3) Lignes SIP classiques 1002 et 1003 | ✅ inchangées : modèles `['global']`, `transport-udp` |
| (4) Avant/après pour les quatre postes | ✅ **aucune différence** : noms d'endpoint, modèles (1001 et 1004 `['webrtc']`), transports, utilisateurs d'authentification et empreintes des secrets identiques à l'état de référence |

Note de sécurité : un relevé intermédiaire de cette étape (commande de diagnostic sur le moteur)
a affiché en clair les secrets SIP des quatre postes de test dans la sortie d'outil de la session
d'assistance ; rien dans le dépôt ni dans ce journal. Ils peuvent être régénérés depuis la
console (Postes → SIP) ; pour 1002 et 1003, les clients `baresip` du laboratoire sont alors à
reconfigurer.

## Rapport d'étape 15 — PR #11 « interception, parcage, interphone, horaires sortants » (Softphone 1.4.0) (22 novembre 2026)

Déployé : `feat/lot-b-pickup-park-intercom` à `4ba3ae5`, **fusionnée localement avec la pointe de
`feat/lot-b-attended-transfer` (`6f26753`)** : la PR avait été coupée avant la réparation
automatique du bug n° 23 et le rapport 14 bis (conflits sur les fichiers générés — client UI et
`openapi.json` — résolus par union). Images `nimbora-pr11` (API, UI), kit lab `--only nimbora
--no-build`, aucune migration. Softphone web **1.4.0** construit depuis la branche (42 tests
Vitest). Comptes de service relancés : dédié **130 ACL** (politique de la PR), opérateur 143,
`POST /pbx/provision` org2 → 200. Sans fusion.

Trois parties comme à l'étape 14 : client = `nimbora-operator` (numéro public pointé selon le
scénario, remis sur 1003 ensuite), employé = 1004 (Softphone web piloté), collègue = 1002 (baresip).

| Scénario | Résultat |
|---|---|
| **1. Interception** — groupe « Accueil » (1002 + 1004) créé via l'API (`*8`) ; appel client → 1002 (sonne) ; sur 1004 « Intercepter » (`*8`) | ✅ 1004 prend l'appel : pont client ↔ 1004, RTP dans les deux sens, 1002 cesse de sonner |
| **2. Parcage** — parking « Accueil » 700, places 701-720, délai 120 s ; pendant un appel client sur 1004 : Transférer → « Parquer · Accueil » | ✅ le client attend en musique (« Started music on hold » sur son canal), pont `parkinglot-1` de type *parking* ; Asterisk : `parking show` → **`parkinglot-1`**, extension 700, places 701-720, contexte interne du tenant ; reprise en composant la place depuis 1002 (`ParkedCall`, pont client ↔ 1002, musique arrêtée) |
| 2. Appel parqué visible dans NIMBORA | ❌ au premier passage : `GET /pbx/parked-calls` vide, Softphone et console vides → 🐛 n° 25 ; ✅ après correctif : API `{lot: Accueil, slot: 70x, number: 0123456789, parked_by: 1004, waiting_seconds}`, Softphone **Récents → Appels parqués** « Place 704 · Accueil · attend depuis 0:08 · Reprendre », console **PBX → Équipe** « Appels parqués — Place 705 — 0123456789 · 0 min 9 s · Accueil » |
| **3. Interphone** — « Directeur », numéro 1 → 1004 ; depuis 1002 composer `*111` | ❌ au premier passage : le PBX raccroche (« Sorry you are not authorize to page this group : Unable to find paging caller entry ») → 🐛 n° 26 ; ✅ après correctif : le Softphone 1004 décroche seul (« Appel entrant » puis « **Interphone** » en moins d'une seconde), pont `softmix` (ConfBridge) 1002 ↔ 1004 avec RTP dans les deux sens |
| 3. En-têtes de l'INVITE reçu par le Softphone (trace JsSIP, identifiants masqués) | `Alert-Info: info=alert-autoanswer` · `Alert-Info: intercom` · `Alert-Info: ring-answer` · `Alert-Info: xivo-autoanswer` · `Alert-Info: <http://wazo.community>;info=alert-autoanswer;delay=0` · **`Call-Info: ;answer-after=0`** · `Answer-Mode: Auto` · `From: "Poste 1002 (SIP, Linphone)"` · `User-Agent: NIMBORA-Voice` |
| **4. Horaires sortants** — interrupteur « Heures d'ouverture » sur la route « Sortie test (lab) » (`PUT /outbound-routes/1/hours`), heures de Mon entreprise mises temporairement à lundi 09:00-10:00 (un dimanche) | ✅ appel sortant de 1002 (`0033…`, route `_00.`) **refusé** : `Congestion` après `check_schedule` |
| 4. Dans les horaires (tous les jours 00:00-24:00) | ✅ l'appel **passe** jusqu'à l'opérateur (pont 1002 ↔ ligne opérateur, RTP) — à condition de **rebasculer l'interrupteur** après avoir changé les heures : l'horaire du PBX est construit au moment du basculement (la docstring le dit), un changement ultérieur des heures du profil n'est pas propagé tant qu'on ne le refait pas. Heures et interrupteur remis ensuite (profil vide, route sans horaire) |

### 🐛 n° 25 — appels parqués invisibles : l'action AMI exige le tenant maître (corrigé)

`wazo-amid` répond 401 `missing_permission_or_invalid_tenant` à toute action (`ParkedCalls`,
mais aussi `Ping`, `QueueStatus`) demandée avec le compte de service d'une entreprise : ses
ressources `/action/*` portent `@required_master_tenant()`. Correction : les appels parqués sont
lus par **wazo-calld** (`GET /parkinglots/{id}`, propre au tenant : `call_id`, `caller_id_num`,
`slot`, `parked_at`, `parker_caller_id_num`…) ; l'ACL `amid.action.ParkedCalls.create` est retirée
de la politique au profit de `calld.parkings.*.read` (toujours 130 ACL) ; faux moteur et tests
adaptés. Même cause pour la **supervision** : `QueueStatus` est refusé lui aussi (`live: false`
sur la file « Support test ») — préexistant, hors PR, à traiter de la même façon (calld ou
agentd).

### 🐛 n° 26 — interphone refusé à tout le monde (corrigé)

Le moteur n'autorise que les appelants **listés** à joindre un interphone : une liste vide ne veut
pas dire « tout le monde », elle interdit tout le monde. Correction : à la création, « tout le
monde » devient tous les postes de l'entreprise ; la liste est réaffichée vide dans NIMBORA quand
elle couvre tout le monde. L'interphone « Directeur » du laboratoire a été recréé après le correctif.

Objets laissés en place sur le laboratoire : parking 700 (701-720) et interphone « Directeur »
(*111). Le groupe d'interception « Accueil » a été **supprimé par erreur pendant cette étape** : le
script de remise en état lancé à 17:10 UTC pour recréer l'interphone après le correctif n° 26
supprimait aussi le groupe (journal wazo-confd : `DELETE /callpickups/1` à 17:10:26, 13 min après
sa création à 16:57:35, par l'API NIMBORA). Il a été recréé à l'étape 18 (`POST /callpickups`
du 23 novembre 06:38:06). Tests API de la branche : 47 passés
(`test_pbx_teamwork.py`, softphone, admin, PBX, dont le test de couverture des ACL).

### 15 bis — supervision par le compte opérateur et horaires qui suivent « Mon entreprise » (`7c2bade`) (22 novembre 2026)

Déployé : pointe `7c2bade` de `feat/lot-b-pickup-park-intercom`, images `nimbora-pr11` (API et
UI) reconstruites, kit lab `--only nimbora --no-build`, aucune migration (tête `d7e8f9a0b1c2`),
aucune ACL nouvelle (comptes inchangés : dédié 130, opérateur 143).

| Étape | Résultat |
|---|---|
| (2) Appel client → file « Support test », agent 1001 en pause (personne de disponible) | ✅ **Supervision en direct** : `live: true`, `waiting: 1`, appelant position 1 avec son numéro et `wait_seconds` 7 puis 18 dix secondes plus tard, `agents_available: 0` |
| (2) Journal de l'API pendant l'appel | ✅ deux `POST amid/1.0/action/QueueStatus` → **200**, zéro 401 : l'AMI est interrogé avec le compte opérateur (tenant maître), uniquement sur les files de l'entreprise |
| (2) Isolation : supervision d'org2 pendant l'attente | ✅ aucune file ni appelant visible pour org2 |
| (3) Interrupteur « Heures d'ouverture » activé sur « Sortie test (lab) » avec des heures lundi 09:00-10:00 (un dimanche) | ✅ confd : `nimbora-horaires-sortie-1` jours [1], plage 09:00-10:00, fermé → `hangup`, attaché à la route 1 |
| (3) Heures changées dans Mon entreprise (tous les jours 00:00-24:00) **sans toucher l'interrupteur** | ✅ journal `[PBX org=1] hours refreshed: nimbora-horaires-1, nimbora-horaires-sortie-1` ; confd : jours [1…7], plage 00:00-23:59 sur les deux horaires ; appel sortant de 1002 **accepté** (pont 1002 ↔ opérateur) |
| (3) Heures remises à lundi 09:00-10:00 (toujours sans toucher l'interrupteur) | ✅ nouveau `hours refreshed`, confd revenu à [1] 09:00-10:00 ; appel sortant de 1002 **refusé** (`Congestion`) |
| (4) Horaire entrant : aucun n'existait, un horaire « Numéros → Appliquer les horaires » (hors horaires → `hangup`) a été posé sur le numéro public pour l'essai | ✅ il suit les mêmes rafraîchissements (`nimbora-horaires-1`, mêmes plages à chaque changement) et **garde sa destination hors horaires** (`hangup`) ; appel entrant hors horaires : `check_schedule` → `CLOSED` « did is out of schedule », l'opérateur reçoit `603 Decline` |
| Remise en état | heures remises à « tous les jours » (dernier rafraîchissement), interrupteur sortant désactivé, horaire entrant détaché du numéro (confd), profil remis vide, numéro public remis sur 1003, agent 1001 remis en service |

Secrets SIP exposés à l'étape 14 bis : rien n'a été régénéré, conformément à la consigne.
Droits temporaires de la session (`/etc/sudoers.d/90-messie-temp`, appartenance au groupe
`docker`) retirés en fin d'étape.

## Rapport d'étape 17 — PR #15 « contrôle qualité des appels humains » (22 novembre 2026)

Déployé **par l'opérateur** (la session d'assistance n'a plus ni `sudo` ni le groupe `docker`
depuis l'étape 15 bis) : `feat/call-quality` à `02aaf0b`, images `nimbora-pr15` (API et UI
construites par la session avant le retrait des droits), migration `a0b1c2d3e4f5` appliquée au
démarrage du conteneur API (avec `e8f9a0b1c2d3` et `f9a0b1c2d3e4` qui la précèdent sur cette
branche). Tests API de la branche (qualité et enregistrements) : 12 passés, lancés avant le retrait
des droits. Toutes les vérifications ci-dessous sont faites sans privilège : API avec les jetons
des comptes du laboratoire, console et Softphone web pilotés en Chromium. Sans fusion.

| Étape | Résultat |
|---|---|
| (1) `GET /api/v1/quality/settings` (org1) | ✅ 200, **6 critères par défaut** (Accueil 1, Écoute et reformulation 2, Vérification de l'identité 1, Réponse apportée 3, Ton et politesse 2, Conclusion 1), évaluation automatique désactivée, échantillon 100 % : les tables sont là |
| (2) Politique d'enregistrement activée (externes entrants et sortants, internes ; pas de suppression sur le PBX, transcription désactivée faute de clé IA) | ✅ 4 postes modifiés |
| (2) Appel humain enregistré | ⚠️ écart par rapport à l'énoncé : les clients `baresip` (1002, opérateur) ne se pilotent plus sans privilèges (`incus exec`) ; l'appel humain a donc été **passé depuis le Softphone web 1004 vers l'opérateur** par la route sortante (`0033…`, décroché automatique), 36 s. « Synchroniser » : l'enregistrement apparaît (`outbound`, 36 s, 577 Ko, `transcript_status: none`) |
| (3) PBX → Enregistrements → « Évaluer » (info-bulle « Pas de transcription : évaluation à l'écoute ») | ✅ ouvre `/quality?review=1`, statut **« À évaluer »**, bouton « Écouter » → lecteur audio sur le lien signé de l'enregistrement, lecture en cours |
| (3) Réponses : Accueil Oui, Écoute En partie, Vérification de l'identité **Sans objet**, Réponse Oui, Ton Oui, Conclusion Non ; « Retour au conseiller » rempli ; **Valider** | ✅ note calculée **77,8 / 100** avant et après validation = (1 + 0,5×2 + 3 + 2 + 0) / (10 − 1 sans objet) : cohérente avec les poids ; statut « Validé » |
| (3) Page Qualité | ✅ Note moyenne 77,8, Appels évalués 1, À valider 0 ; onglet **Conseillers** : 1 appel évalué, 1 validé, 77,8 ; onglet Appels évalués : 22/11 21:22, 36 s, Validé, note IA —, note retenue 77,8 |
| (4) Isolation (API) : org2 et org3 | ✅ `GET /quality/reviews` → 0, `GET /quality/reviews/1` → **404**, `GET /quality/summary` → tout à zéro, `GET /pbx/recordings` → 0 |
| (4) Isolation (console) : connexion entreprise-a, `/quality` | ✅ compteurs à zéro, aucune table d'appels, `/quality?review=1` n'ouvre aucune fiche |
| (5) Évaluation par l'IA, « Réévaluer avec l'IA », évaluation automatique « À valider » après import | 🧪 clés fournisseur IA non disponibles (et transcription désactivée) |
| (6) Remise en état | ✅ Enregistrements → corbeille sur l'enregistrement d'essai (« Enregistrement supprimé », son évaluation disparaît avec lui), politique d'enregistrement remise à son état initial (tout désactivé, 4 postes modifiés), aucun enregistrement ni évaluation restants |

### 🐛 n° 27 — conseiller d'un appel sortant = numéro public (corrigé, à revalider)

Dans l'onglet Conseillers et sur la fiche, le conseiller de l'appel sortant est
« 2250700000001 · 2250700000001 », c'est-à-dire le **numéro présenté par la route sortante**, et
non le poste 1004 qui a passé l'appel. Cause : l'import des enregistrements remplit `source`
avec `source_extension` du journal d'appels du moteur ; pour un appel sortant c'est le numéro
externe présenté, le poste est dans `source_internal_extension` (même piège que le bug n° 20 de
l'étape 9 pour le conseiller habituel). `agent_of` prend ensuite `source` pour un `outbound`.
Correction proposée : à l'import, préférer `source_internal_extension` / nom interne pour la
source d'un appel sortant (et `destination_internal_extension` pour un entrant), ou stocker
l'extension interne à part ; test avec la forme réelle du CDR. Non corrigé ici : sans
privilèges, ni redéploiement ni tests en conteneur possibles.

**Correction** (après l'étape 17) : `recordings.call_parties` prend, de chaque côté de l'appel,
`<côté>_internal_extension` avant `<côté>_extension`, et écarte un nom qui n'est que ce
numéro ; test `test_the_advisor_is_the_internal_extension_not_the_public_number` avec la forme
du CDR relevée au labo. Les enregistrements déjà importés gardent leur ancienne valeur.

### 17 bis — n° 27 et non-réimportation revalidés (`098737d`) (22 novembre 2026)

Déployé par l'opérateur (images API et UI reconstruites depuis `098737d`, conteneurs recréés,
`alembic current` = `b1c2d3e4f5a6`). Vérification sans privilèges que la nouvelle API répond
bien : son `openapi.json` contient la nouvelle description de `DELETE /pbx/recordings/{id}`
(« never comes back »). Un premier passage, fait alors que l'ancienne image tournait encore,
avait montré l'ancien comportement (réimportation, source = numéro public) : il est sans objet.

| Étape | Résultat |
|---|---|
| (1) Enregistrements 7, 8, 9, 10 (importés par l'ancienne image) supprimés depuis la console | ✅ confirmation « Supprimer définitivement cet enregistrement, **ici et sur le PBX** ? », toast « Enregistrement supprimé » ; deux « Synchroniser » : `seen 5, imported 0`, **aucun ne revient** |
| (2) Nouvel appel sortant Softphone web 1004 → opérateur (37 s), « Synchroniser » | ✅ enregistrement 12 : **source `1004`** (plus le numéro public), destination `0033…`, client `+33…` |
| (3) Appel entrant client → 1003 passé par l'opérateur (29 s) | ✅ enregistrement 11 : destination (conseiller) **`1003`** ; ❌ **sans son nom** → 🐛 n° 28 |
| (4) PBX → Enregistrements → « Évaluer » sur l'appel sortant | ✅ fiche **« 1004 »** ; validation à l'écoute (mêmes réponses qu'à l'étape 17) → 77,8 / 100 ; page Qualité : Conseillers « 1004 », 1 appel validé |
| (5) Remise en état | ✅ enregistrements 11 et 12 supprimés depuis la console, deux synchronisations sans retour (`seen 6, imported 0`), aucune évaluation restante, politique d'enregistrement remise à son état initial (4 postes modifiés) |

### 🐛 n° 28 — le nom du conseiller disparaît quand il contient son numéro (corrigé sur la branche)

Le filtre du n° 27 (« un nom qui n'est que le numéro ne dit rien ») comparait les **chiffres**
du nom avec l'extension : « Test 1003 (SIP, répondeur automatique) » et « Poste 1004
(navigateur, test présence) » perdaient donc leur nom. Correction : seul un nom qui n'est
qu'un numéro, quelle que soit son écriture (« 2250700000001 », « +225 07 00 00 00 01 »,
« 1004 »), est ignoré ; test unitaire complété. Vérifié sur les fonctions pures en dehors de la
suite (pytest en conteneur impossible sans privilèges) : le nom des postes 1003 et 1004 est
conservé, les numéros nus sont écartés. À redéployer pour le voir sur le laboratoire.

## Rapport d'étape 16 — PR #12 (catalogue), #13 (prospects), #14 (AI Business Hub), #16 (version en service) (22 novembre 2026)

Déployé par l'opérateur depuis `chore/deploy-build-stamp` (`e6dbf05`, qui contient les PR #8 à
#15 et le correctif n° 28). Session d'assistance sans `sudo` ni `docker` : vérifications par
l'API (jetons des comptes du laboratoire) et par la console pilotée en Chromium. Sans fusion.

| Étape | Résultat |
|---|---|
| (0) `GET /api/v1/health` → `build_commit` | ❌ **la réponse ne contient aucun champ `build_commit`** (clés : `auth_provider`, `backend_api_endpoint`, `deployment_mode`, `force_turn_relay`, `signup_enabled`, `stack_*`, `status`, `tunnel_url`, `turn_enabled`, `version`). L'API en service n'est donc pas construite depuis `e6dbf05` (la PR #16 ajoute ce champ, `None` au pire). Dernière ligne d'`install.sh` : non fournie. Les points suivants ont été vérifiés sur l'API en service, qui expose déjà le catalogue, les prospects et le hub |
| (1) Catalogue : 3 articles créés par l'API (85 000 XOF « la nuit » avec caractéristiques, 25,50 EUR, 4 500,75 XOF) | ✅ le prix XOF à décimales est arrondi à **4 501** ; console `/catalog` : « 85 000 F CFA », « 4 501 F CFA », « 150 000 F CFA », « 25,50 € », article à stock 0 marqué « Épuisé » |
| (1) Import CSV de 2 lignes (en-têtes français, séparateur `;`) | ✅ `created 2, updated 0, errors []` ; export : en-tête `reference;nom;type;categorie;description;prix;devise;unite;stock;disponible;url;tags;…` + les colonnes de caractéristiques, 5 lignes d'articles |
| (1) Recherche « délux » | ✅ trouve « Chambre Deluxe vue mer » (API et console) ; « aeroport » trouve « Transfert aéroport » |
| (1) Isolation org2 | ✅ 0 article, recherche vide, `PUT` sur un article d'org1 → 404 |
| (2) Prospects : 2 créés (XOF avec fourchette de budget, EUR) ; le premier avancé `qualified → proposal → negotiation → won` | ✅ pipeline : Nouveau 1, Gagné 1 (les quatre autres à 0) ; console `/leads` : six colonnes, « Gagné · 2 500 000 F CFA · Awa Koné · Chaud · 95 », « Nouveau · 400,00 € · Jean Dupont · Tiède · 60 » ; `?stage=won` horodaté |
| (2) Export CSV | ✅ en-tête `id;nom;telephone;email;societe;besoin;budget;echeance;decideur;interets;etape;score;source;responsable;prochaine action;cree le`, budget « 1 500 000 F CFA à 2 500 000 F CFA », étape « Gagné » |
| (2) Isolation org2 | ✅ 0 prospect, pipeline vide, `PUT` et changement d'étape sur un prospect d'org1 → 404 |
| (3) Hub `/hub` : 6 indicateurs (Conversations, Appels IA, Appels humains, Rendez-vous pris, Nouveaux prospects, Nouveaux clients) sur 7 → 30 → 90 jours (`period=7d|30d|90d`, 7/30/90 lignes quotidiennes) | ✅ valeurs stables sur les trois périodes (toute l'activité du laboratoire date de 48 h) ; « Nouveaux prospects 2 · 1 qualifiés · 1 gagnés (50 %) » pendant l'essai ; vue **Tableau** (Jour / Appels IA / Appels humains / WhatsApp / Web / Rendez-vous / Prospects) |
| (3) Appels humains vs PBX | ⚠️ hub : **34** appels humains, 18 min (source : lignes `human_call_usage`) ; journal d'appels du PBX : **35** appels externes décrochés (28 entrants + 7 sortants), 17,9 min. Un appel d'écart, mêmes minutes : à dater côté auteur (dernier appel non encore comptabilisé, ou appel « décroché » par le PBX lui-même). Les 16 appels internes décrochés ne sont pas comptés, ce qui est attendu |
| (3) Fuseau | ✅ « Conversations par canal (jours dans le fuseau UTC) » = fuseau de Mon entreprise (UTC) |
| (3) Isolation org2 | ✅ conversations 0, appels IA 0, appels humains 0, rendez-vous 0, prospects 0 ; « Nouveaux clients 1 » correspond au seul client d'org2 (appel manqué de l'étape 9) |
| (4) n° 28 (nom du conseiller 1003) | 🧪 aucun nouvel appel entrant client → 1003 pendant l'étape, et l'API en service n'est pas celle de `e6dbf05` (voir point 0) |
| (5) Outils d'agent `search_catalog` et `qualify_lead` en appel réel | 🧪 clés fournisseur IA non disponibles |
| (6) Remise en état | ✅ 5 articles et 2 prospects supprimés (0 restant), aucun enregistrement d'essai |

### 16 bis — version en service, écart du hub, n° 28 (`25b4aee`) (22 novembre 2026)

Déployé par l'opérateur avec le kit (construction marquée du commit). Session sans `sudo` ni
`docker` : API et console seulement.

| Étape | Résultat |
|---|---|
| (0) `GET /api/v1/health` | ✅ `build_commit: "25b4aee"` (après un court redémarrage de l'API pendant lequel la route n'a pas répondu) |
| (1) Écart du hub (34 appels humains contre 35 appels externes décrochés dans le journal du PBX) | ✅ **confirmé : l'appel absent est le n° 5** (21 novembre 23:03, entrant, décroché, 18 s, destination « Test 1003 (SIP, répondeur automatique) »). Le fichier fourni par l'auteur (`id|début|durée|sens`, 34 lignes, 17,6 min) contient tous les autres identifiants du journal et aucun en trop. Sa source est l'identité brute **« operator »**, sans aucun chiffre : elle a été prise pour un poste et l'appel n'a pas été compté comme appel humain. Cohérent avec l'hypothèse de l'auteur et le correctif de `25b4aee` (identité sans chiffre = client au numéro masqué) ; les appels déjà passés ne sont pas recomptés |
| (2) n° 28 — appel entrant client → 1003 (28 s, journal n° 90) passé par l'opérateur, politique d'enregistrement activée avant, « Synchroniser » | ✅ enregistrement 13 : destination (conseiller) **« 1003 »** avec son nom **« Test 1003 (SIP, répondeur automatique) »** |
| (2) Hub après cet appel | ✅ appels humains **34 → 35** (conversations 35), minutes 18 : le nouvel appel est compté |
| (3) Remise en état | ✅ enregistrement 13 supprimé depuis la console (« ici et sur le PBX »), synchronisation sans retour (`seen 7, imported 0`), politique d'enregistrement remise à son état initial (4 postes modifiés), 0 enregistrement |

## Rapport d'étape 18 — laboratoire revenu sur `main` (`948f1e8`, PR #1 à #16 fusionnées) (23 novembre 2026)

Déployé par l'opérateur avec le kit (REGISTRY retiré du `.env`, images sous le nom par défaut).
Session sans `sudo` ni `docker` : API avec les jetons du laboratoire, console et Softphone web
pilotés en Chromium. Softphone web 1.4.0 construit depuis `main`.

| Étape | Résultat |
|---|---|
| (1) `GET /api/v1/health` → `build_commit` | ✅ **`948f1e8`** (vérifié le 23 novembre, après la relance du kit). À la première vérification la route affichait encore `25b4aee` : le déploiement depuis `main` n'avait pas tourné, le kit s'étant arrêté en silence juste après ses avertissements (`get_kv` échouait sur la clé `REGISTRY` retirée du `.env`, sous `set -euo pipefail`), défaut introduit par la PR #16 et corrigé par la PR #18 (non fusionnée) ; l'opérateur a remis `REGISTRY=nimbora` et relancé le kit |
| (2) Console org1 : PBX → Postes | ✅ quatre postes et deux appareils Softphone listés, présence 1001 « Hors ligne », 1002 « Disponible », 1003 « Disponible », 1004 « Hors ligne » (application fermée) |
| (2) PBX → Routage | ✅ onglet, politique et simulateur rendus |
| (2) PBX → Équipe | ✅ parking « Accueil » 700 (701-720) et interphone « Directeur » (`*111`) présents ; le groupe d'interception « Accueil » (1002 + 1004) de l'étape 15 était absent du moteur : d'après le journal wazo-confd fourni par l'opérateur (tenant de l'entreprise, user-agent de l'API NIMBORA), il a été créé le 22 novembre à 16:57:35 UTC puis **supprimé à 17:10:26 UTC par le script de remise en état de la session d'assistance** (qui recréait l'interphone et supprimait aussi le groupe), pas par une annulation automatique ; recréé ici le 23 novembre à 06:38:06 UTC (`POST /callpickups` → 201, identifiant 1) |
| (2) PBX → Enregistrements | ✅ bloc politique affiché, « Aucun enregistrement » |
| (2) Catalogue, Prospects, AI Business Hub, Contrôle qualité | ✅ les quatre pages s'ouvrent sans erreur de page, sans réponse 5xx ni toast d'erreur ; hub : 6 indicateurs (35 appels humains, 35 conversations), qualité : 4 compteurs, catalogue et prospects vides |
| (2) Softphone web 1004 | ✅ « Disponible » ; appel 1004 → 1002 : « Ça sonne… » (1002 est un client `baresip` à décroché manuel, non pilotable sans privilèges : appel non établi, raccroché) ; appel 1004 → 1003 (décroché automatique) **établi** 20 s puis « Appel terminé » |
| (3) Isolation : même parcours connecté comme entreprise-a (org2) | ✅ Postes : seul « Agent A 1001 » ; Équipe : aucun groupe, parking ni interphone ; Enregistrements vides ; catalogue 0, prospects 0, hub tout à zéro, qualité 0 ; aucune erreur de page |

Aucun appel ni objet d'essai laissé en place (le groupe « Accueil » recréé est un objet du
laboratoire, comme le parking et l'interphone).

## Rapport d'étape 19 — PR #19 « tests des agents avec des clients simulés » (23 novembre 2026)

Déployé par l'opérateur avec le kit depuis `feat/agent-simulated-tests` (`d981adf`, qui contient
`main` à `c2d4b5f`) ; migration `c2d3e4f5a6b7` appliquée au démarrage. Session sans `sudo` ni
`docker` : API avec les jetons du laboratoire, console pilotée en Chromium. Sans fusion.

Préalable : aucun agent n'existait sur le laboratoire ; un agent « Agent test labo (étape 19) » a
été créé pour org1 depuis le modèle métier « Accueil général » (`POST /business/templates/general/agent`,
outils `schedule_callback` et `transfer_call` signalés manquants donc non attachés), puis archivé en fin d'étape.

| Étape | Résultat |
|---|---|
| (1) `GET /api/v1/health` → `build_commit` ; `GET /api/v1/agent-tests?workflow_id=1` | ✅ `d981adf` ; 200 (liste vide) — une première vérification faite alors que `main` seul tournait (`c2d4b5f`) donnait 404 : la fonctionnalité n'y est pas |
| (2) Agent → menu ⋮ (icône MoreVertical de l'éditeur) | ✅ entrées « View Runs · **Tests clients simulés** · Duplicate Workflow · Download Workflow · Copy Agent UUID » ; l'entrée ouvre `/workflow/1/tests` |
| (2) « Nouveau test » : nom, client décrit (persona), 2 critères de réussite, 1 phrase interdite → « Enregistrer le test » | ✅ « Test enregistré », une ligne dans le tableau |
| (2) « Modifier » : nom changé, troisième critère ajouté | ✅ ligne mise à jour |
| (2) « Lancer » (version brouillon) | ✅ statut **« Erreur »** en moins de 5 s ; fiche du lancement : « Erreur · Brouillon · **Aucun modèle de langage utilisable : vérifiez-le dans Modèles IA** (Invalid model configuration; review fields: llm) » ; API : `last_run.status = error` avec le même message |
| (2) « Proposer des tests » | ✅ toast avec le **même message**, pas de dialogue de suggestions, aucune erreur de page ni réponse 5xx ; API `POST /agent-tests/suggest` → 409 avec le même détail |
| (3) Isolation : org2 (et org3) | ✅ `GET /agent-tests?workflow_id=1` → **404** « Agent introuvable » ; `POST /agent-tests` et `POST /agent-tests/suggest` sur l'agent d'org1 → 404 |
| (4) Lancement avec une clé : verdict par critère et conversation | 🧪 clés fournisseur IA non disponibles |
| Nom de fonction d'un outil accentué | ✅ la fonction `custom_tool_function_name` de la PR, exercée hors de l'API sur le code de la branche : « Réserver » → **`reserver`**, « Prendre rendez-vous » → `prendre_rendez_vous`, « Créer un ticket » → `creer_un_ticket` (test unitaire `test_agent_tests.py` présent). L'affichage dans la fiche d'un lancement (« Utilise l'outil … », « Outils utilisés ») n'a pas pu être observé : il faut un agent avec un outil personnalisé attaché et un modèle de langage — 🧪 pour cette partie |
| (5) Remise en état | ✅ test supprimé depuis la console (confirmation « Supprimer le test … et ses résultats ? », « Aucun test. »), 0 test par l'API ; agent d'essai archivé (`PUT /workflow/1/status`) |

## Rapport d'étape 20 — PR #21 « SeaweedFS par défaut » (23 novembre 2026)

Déployé par l'opérateur : volume MinIO sauvegardé, branche `feat/seaweedfs-default` (`50a10f9`)
déployée avec le kit (MinIO conservé), puis `OBJECT_STORE=seaweedfs` et les étapes `copy`,
`verify`, `switch` de l'outil de migration. Session sans `sudo` ni `docker` : API avec les jetons
du laboratoire, console et Softphones web pilotés en Chromium. Sans fusion.

| Étape | Résultat |
|---|---|
| (1) `GET /api/v1/health` | ✅ `build_commit: "50a10f9"`, **`object_store: "seaweedfs"`**, **`legacy_minio_files: 0`**. Sorties de la migration (opérateur) : **copy** « 1 objets (16044 octets) : 1 copiés, 0 déjà présents, 0 manquants, 0 de taille différente » ; **verify** « 1 objets (16044 octets) : 0 copiés, 0 déjà présents, 0 manquants, 0 de taille différente » ; **switch** « Lignes mises à jour : {'workflow_runs': 0, 'workflow_recordings': 0, 'pbx_call_recordings': 0} ». L'unique objet copié n'était référencé par aucune ligne (reste d'un essai antérieur) : aucun fichier en service à migrer, cohérent avec `legacy_minio_files: 0` |
| (2) Anciens fichiers importés avant la migration | 🧪 **aucun fichier antérieur sur le laboratoire** : 0 enregistrement (tous supprimés aux étapes précédentes), 0 document de base de connaissances, 0 enregistrement d'appel IA ; `legacy_minio_files: 0` est cohérent. Rien à écouter ni à ouvrir d'ancien |
| (3) Nouveau document : `POST /knowledge-base/upload-url` → lien de dépôt signé sur `app.optimiumnexus.com/voice-audio/knowledge_base/1/…` ; `PUT` du fichier texte (121 octets) | ✅ 200, en-tête **`Server: SeaweedFS 30GB 4.55`**, ETag renvoyé ; `process-document` → document listé, contenu relu par l'API ; `GET /s3/signed-url` → lien signé ouvert : 200 `text/plain`, même serveur, contenu intact. ⚠️ `processing_status: failed` avec « Add a NIMBORA provider with a service key to use this feature » : l'indexation exige un fournisseur hébergé ou une clé IA, absents du laboratoire (hors stockage) |
| (3) Nouvel appel humain enregistré | ✅ politique d'enregistrement activée, appel **Softphone web 1004 → Softphone web 1001** (33 s, décroché sur 1001 ; les clients `baresip` du laboratoire étaient arrivés au bout de leur durée de vie de 24 h et ne se relancent pas sans privilèges) ; « Synchroniser » → enregistrement 14 (`internal`, 1004 → 1001, 533 804 octets) |
| (3) Écoute | ✅ `GET /pbx/recordings/14/audio` → lien signé `https://app.optimiumnexus.com/voice-audio/pbx-recordings/1/2026/11/23/…` (paramètres `X-Amz-*`, `response-content-type`, `response-content-disposition`) ; lecture : 200, `audio/wav`, 533 804 octets, en-tête **`Server: SeaweedFS 30GB 4.55`**, en-tête RIFF : servi par SeaweedFS derrière Traefik |
| (4) Sécurité | ✅ même clé **sans paramètres de signature → 403 `AccessDenied`** ; **signature modifiée → 403 `SignatureDoesNotMatch`** (pour l'enregistrement comme pour le document) |
| (5) Isolation | ✅ org2 : `GET /pbx/recordings/14/audio` → 404, liste des enregistrements vide, `GET /knowledge-base/documents/{uuid d'org1}` → 404, 0 document |
| Remise en état | ✅ enregistrement 14 supprimé depuis la console (« ici et sur le PBX »), synchronisation sans retour, document supprimé, politique d'enregistrement remise à son état initial, 0 enregistrement et 0 document |

### Fin d'étape — MinIO retiré

L'opérateur a ajouté `MINIO_RETIRED=true` et relancé le kit : **MinIO retiré, volume et sauvegarde
conservés**. Vérifié ensuite sans privilèges : `GET /api/v1/health` → `object_store: "seaweedfs"`,
`legacy_minio_files: 0` ; un document téléversé (lien de dépôt signé, `PUT` 200 servi par
« SeaweedFS 30GB 4.55 », `process-document` 200) se relit par lien signé (200, `text/plain`, même
serveur) et reste refusé sans signature (403) ; document supprimé ensuite, 0 restant.

### 20 bis — MinIO vraiment arrêté, image SeaweedFS épinglée (`8de7a2f`) (24 novembre 2026)

🐛 Défaut trouvé par l'opérateur : le MinIO « retiré » (`MINIO_RETIRED=true`) **tournait encore**,
car `compose up` n'arrête pas un service dont le profil est désactivé. Corrigé dans `8de7a2f` : le
kit supprime le conteneur avant `up` (conteneur seulement, volume conservé). Le même commit épingle
l'image : **`chrislusf/seaweedfs:4.55@sha256:7ca46aeae2f223b37e5d91593c17ab37738eec6df6ab69b48a0487f7643342b9`**
(empreinte relevée par l'opérateur avec `docker image inspect … RepoDigests`).

| Vérification | Résultat |
|---|---|
| (1) `GET /api/v1/health` | `object_store: "seaweedfs"`, `legacy_minio_files: 0` ✅ ; `build_commit` ✅ **`8de7a2f`** d'après la sortie du kit relancé par l'opérateur (« image nimbora/nimbora-api:latest (8de7a2f) », puis « API en service construite depuis 8de7a2f », valeur que le kit lit sur cette même route). Une lecture antérieure à cette relance affichait encore `50a10f9`. Le kit reconstruit les images à chaque passage (sauf `--no-build`), même quand le commit ne touche pas `api/` |
| (2) Conteneurs | ✅ sortie du kit de l'opérateur : `docker ps -a … \| grep -c nimbora_minio` → `0`, volume `nimbora-lab_minio-data` toujours listé ; `nimbora_seaweedfs` healthy |
| (3) Document téléversé puis relu, MinIO arrêté pour de bon | ✅ `PUT` 200 (« SeaweedFS 30GB 4.55 »), `process-document` 200, relecture par lien signé 200 `text/plain`, 403 sans signature ; document supprimé, 0 restant |

## Rapport d'étape 21 — PR #28 « charte de l'interface » et PR #30 « contrôle des mentions du moteur » (24 novembre 2026)

Déployé par l'opérateur : `feat/ui-charter` (`dadc44f`) avec une charte d'essai (`BRAND_NAME=Acme Voix`,
symbole et favicon `/brand-assets/acme-mark.svg`, couleur `#0a7d4f`, dégradé `#0a7d4f,#11a36b,#7bd389`).
Session sans `sudo` ni `docker` : requêtes HTTP et Chromium sans interface. Sans fusion.

| Étape | Résultat |
|---|---|
| (1) `GET /api/v1/health` | ✅ `build_commit: "dadc44f"` (une première lecture, avant le déploiement, donnait `8997cd8` et une page sans charte : sans objet) |
| (2) `GET /auth/login` | ✅ `<title>` « Acme Voix — Centre d'appels IA » ; `<style id="brand-charter">` avec `--primary: #0a7d4f` et les trois couleurs du dégradé ; `<link rel="icon" href="/brand-assets/acme-mark.svg">` (et `apple-touch-icon` identique) ; 14 occurrences de « Acme Voix », aucune « NIMBORA » visible. ⚠️ une occurrence « NIMBORA » subsiste dans les données de la page : `pbxName: "NIMBORA Voice"`, nom du PBX laissé par défaut par la charte d'essai (variable `PBX_NAME`), non affiché sur la page de connexion |
| (3) `GET /brand-assets/acme-mark.svg` | ✅ 200, `content-type: image/svg+xml`, `x-content-type-options: nosniff`, `content-security-policy: default-src 'none'; style-src 'unsafe-inline'; sandbox` |
| (3) `GET /brand-assets/../.env` et `/brand-assets/secrets.env` | ⚠️ **307 vers `/auth/login`** (puis 200 sur la page de connexion), et non 404 : l'intergiciel d'authentification de l'UI intercepte ces chemins avant la route des fichiers de charte (le `..` ramène à `/.env`, et `secrets.env` n'a pas une extension de fichier de charte). Rien n'est servi, aucun contenu ne fuit ; le code attendu était 404. `/brand-assets/nope.svg` (nom inconnu, bonne extension) → **404** |
| (4) Capture de `/auth/login` (Chromium sans interface, `login-acme.png`) | ✅ logo `acme-mark.svg` (alt « Acme Voix ») en haut et dans le panneau ; bouton « Se connecter » en vert `rgb(10, 125, 79)` avec dégradé `#0a7d4f → #11a36b → #7bd389` ; aucune image ni attribut mentionnant NIMBORA ; accroche « Le centre d'appels qui pense, parle et décide. » |
| (5) Contrôle des mentions du moteur (PR #30) | ⏳ **sortie non transmise à la session** : aucune ligne MENTION/ERREUR ni code de sortie à rapporter pour l'instant ; rien n'a été modifié sur le PBX |

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

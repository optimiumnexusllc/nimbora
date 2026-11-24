# Laboratoire : PBX et plateforme sur un seul serveur

Ce kit installe le **PBX d'entreprise en marque blanche** (`deploy/pbx/`) et la **plateforme
NIMBORA** sur **un seul serveur déjà occupé**, sans toucher à ce qui y tourne. Il sert à
valider la phase 5 et à faire des démonstrations quand on n'a pas de serveur Debian 12
dédié. Pour la production, gardez un serveur dédié au PBX (`deploy/pbx/README.md`).

```
 Internet ──► pare-feu de l'hébergeur ──► serveur (Ubuntu/Debian, Docker, Traefik existant)
                                           │
   443 app.votre-domaine ──► Traefik ──────┼──► nimbora_ui / nimbora_api / nimbora_seaweedfs  (Docker, réseau br-nimboralab)
   443 pbx.votre-domaine ──► Traefik ──────┼──► 10.250.0.10:443  nginx du PBX  ─┐
   RTP 10000-20000/udp ──► DNAT ───────────┼──► 10.250.0.10      Asterisk       │ conteneur Incus « nimbora-pbx »
                                           │                                     │ Debian 12, 2 vCPU, 4 Go
                       nimbora_api ───────►┼──► 10.250.0.10:5039 ARI (privé)    ─┘
```

- Le **PBX** tourne dans un **conteneur système Incus** (Debian 12), seul environnement que
  le kit `deploy/pbx/` accepte. Il a une IP privée fixe sur le pont `incusbr0`.
- La **plateforme** tourne en Docker Compose, **derrière le Traefik déjà présent** (celui de
  Coolify par défaut) : aucun port 80/443 republié, un seul fichier déposé dans le dossier
  dynamique de Traefik, certificats Let's Encrypt obtenus par Traefik.
- **L'ARI du PBX n'est jamais exposé** : NIMBORA le joint par le réseau privé, et le pare-feu
  de l'hôte interdit à toute autre application Docker d'atteindre le PBX, sauf Traefik sur
  son HTTPS.
- Sur l'hôte, le kit n'ajoute que : Incus, un service systemd de règles `DOCKER-USER` et de
  redirection RTP (idempotent, marqué `nimbora-lab`), un réglage sysctl.

## 1. Prérequis

| | |
|---|---|
| Serveur | Ubuntu 22.04/24.04 ou Debian 12, Docker et Docker Compose v2, **7 Go de RAM disponibles**, 20 Go de disque |
| Traefik | existant, fournisseur `file` avec `watch` sur un dossier, résolveur ACME `letsencrypt`, entrées `http` et `https` (c'est la configuration de Coolify) |
| DNS | `app.<domaine>` et `pbx.<domaine>` pointent vers l'IPv4 du serveur |
| Pare-feu | voir la liste des ports ci-dessous, à ouvrir **chez l'hébergeur** (Hostinger, OVH, Hetzner…). Option `--ufw` pour un hébergeur sans pare-feu externe |

### Ports à ouvrir chez l'hébergeur

| Port | Protocole | Usage | Source |
|---|---|---|---|
| 22 | TCP | SSH | vos adresses d'administration |
| 80, 443 | TCP | plateforme, PBX (API, softphones), défi Let's Encrypt | tout Internet |
| 443 | UDP | HTTP/3 de Traefik | tout Internet |
| 3478, 5349 | TCP et UDP | TURN (WebRTC de la plateforme) | tout Internet |
| 49152-49200 | UDP | relais TURN | tout Internet |
| 10000-20000 | UDP | **RTP** : audio des téléphones et softphones du PBX | tout Internet |
| 5060 UDP/TCP, 5061 TCP | | **SIP** : seulement quand un opérateur est raccordé (`--sip-public`) | adresses de l'opérateur |

Les ports des autres applications du serveur ne sont pas concernés par ce kit. Tout ce qui
n'est pas dans cette liste doit être fermé en amont ; l'ARI (5039) et l'AMI (5038) du PBX
n'y figurent pas et ne doivent jamais y figurer.

## 2. Installer

```bash
git clone https://github.com/optimiumnexusllc/nimbora.git /opt/nimbora && cd /opt/nimbora/deploy/lab
sudo ./install.sh --app-domain app.votre-domaine.com --pbx-domain pbx.votre-domaine.com \
  --brand "NIMBORA" --company "Entreprise test" \
  --secrets-file /root/nimbora-lab-secrets.env     # clés des fournisseurs d'IA (optionnel)
```

| Option | Rôle (défaut) |
|---|---|
| `--app-domain`, `--pbx-domain` | noms publics de la plateforme et du PBX |
| `--brand`, `--company` | marque et première entreprise du PBX |
| `--bridge-cidr`, `--pbx-ip` | pont Incus (`10.250.0.1/24`) et adresse du PBX (`10.250.0.10`) |
| `--pbx-memory`, `--pbx-cpu` | limites du conteneur (`4GiB`, `2`) |
| `--traefik-dynamic-dir`, `--traefik-network` | Traefik existant (`/data/coolify/proxy/dynamic`, `coolify`) |
| `--deploy-dir`, `--workers` | pile NIMBORA (`/opt/nimbora-lab`, `2` workers API) |
| `--secrets-file` | fichier `CLE=valeur` fusionné dans le `.env` de la pile (clés d'IA…) |
| `--rtp-range` | plage RTP redirigée vers le PBX (`10000-20000`) |
| `--sip-public` | redirige aussi SIP 5060/5061 vers le PBX (opérateur raccordé) |
| `--ufw` | installe UFW avec la liste de ports ci-dessus (hébergeur sans pare-feu) |
| `--only incus,firewall,pbx,nimbora,traefik` | ne joue que ces phases |
| `--shared-pbx` | PBX partagé de l'opérateur : moteur installé avec `--operator`, compte d'approvisionnement et `PBX_PROVISIONING_*` écrits dans le `.env` de la pile ; chaque entreprise active ensuite sa téléphonie en un clic |
| `--no-build` | ne reconstruit pas les images Docker |
| `--force-pbx` | relance l'installateur du moteur dans un conteneur déjà installé |

Le script est **re-jouable** : il ne refait que ce qui manque. Ses paramètres sont gardés
dans `/etc/nimbora-lab/lab.env`, les secrets du PBX copiés dans `/etc/nimbora-pbx/` du
conteneur et `/etc/nimbora-lab/` de l'hôte (root uniquement).

Ce qu'il fait, dans l'ordre :

1. **preflight** : interface et IP publiques, réseau et pont de Traefik, DNS, mémoire ;
2. **incus** : paquet `incus`, stockage `dir`, pont `incusbr0` en NAT, sysctl inotify ;
3. **firewall** : `/usr/local/sbin/nimbora-lab-firewall` et son service systemd, lancé
   après Docker et Incus et à chaque redémarrage de Docker (voir `firewall.sh`) ;
4. **pbx** : conteneur Debian 12, kit `deploy/pbx/` poussé et exécuté avec
   `--nimbora-ip` = adresse de l'hôte sur le pont (toute la plateforme sort par là), puis
   `scripts/pbx_nat.py` : adresse publique sur les transports SIP, réseau local, plage RTP ;
5. **nimbora** : `.env` généré (secrets gardés d'une exécution à l'autre), images
   construites depuis le dépôt, override Compose (aucun port publié sauf TURN, API et UI
   rattachées au réseau de Traefik, route par défaut par le pont `br-nimboralab`) ;
6. **traefik** : `nimbora-lab.yaml` dans le dossier dynamique, attente des certificats.

## 3. Relier la plateforme au PBX

Le résumé affiché à la fin donne les valeurs. Puis suivez la section 3 de
[`deploy/pbx/README.md`](../pbx/README.md) avec ces particularités :

- **Asterisk ARI** : `http://10.250.0.10:5039` (privé). Le pare-feu du PBX n'accepte l'ARI
  que depuis `10.250.0.1`, l'adresse sous laquelle la plateforme sort du serveur.
- **Connexion Téléphonie d'entreprise** : `https://10.250.0.10` avec la vérification du
  certificat désactivée (certificat auto-signé du moteur), ou `https://pbx.<domaine>` par
  Traefik.
- **Softphones** : Postes → Softphones → adresse WebSocket `wss://pbx.<domaine>/api/asterisk/ws`,
  domaine SIP `pbx.<domaine>` : les navigateurs exigent le certificat Let's Encrypt de Traefik.

## 4. Pare-feu de l'hôte, en détail

Docker et Incus se partagent la chaîne `FORWARD`. Docker y refuse tout ce qu'il ne connaît
pas, dont le pont d'Incus ; le kit ajoute donc ses règles dans `DOCKER-USER`, évaluée en
premier et jamais vidée par Docker :

| Ordre | Règle | Pourquoi |
|---|---|---|
| 1 | tout ce qui vient d'`incusbr0` | le PBX joint Internet, les opérateurs et la plateforme (par son nom public) |
| 2 | réponses vers `incusbr0` | sessions déjà établies |
| 3 | `eth0 → PBX`, UDP 10000-20000 | RTP redirigé (règle DNAT associée) |
| 4 | `eth0 → PBX`, 5060/5061 | seulement avec `--sip-public` |
| 5 | `br-nimboralab → PBX` | la plateforme : API REST, ARI, webhooks |
| 6 | `pont de Traefik → PBX:443` | Traefik sert `pbx.<domaine>` |
| 7 | `br-nimboralab → pont de Traefik`, 80/443 | la plateforme s'appelle par son nom public |
| 8 | tout autre `→ incusbr0` refusé | **aucune autre application Docker n'atteint le PBX** (ARI, AMI) |

Les règles portent le commentaire `nimbora-lab` : `iptables -S DOCKER-USER | grep nimbora-lab`.
Le service se relance à chaque redémarrage de Docker (`PartOf=docker.service`).

## 5. Exploitation

```bash
sudo incus exec nimbora-pbx -- wazo-service status       # services du moteur
sudo incus exec nimbora-pbx -- asterisk -rx 'pjsip show transports'
sudo cat /etc/nimbora-lab/pbx-secrets.env                 # secrets du PBX (root)
(cd /opt/nimbora-lab && sudo docker compose ps && sudo docker compose logs -f api)
sudo systemctl status nimbora-lab-firewall
sudo incus snapshot create nimbora-pbx avant-maj          # instantané du PBX
```

Mise à jour de la plateforme : `git pull` puis `sudo ./install.sh --only nimbora` (les
secrets du `.env` sont conservés, les migrations de base s'appliquent au démarrage de
l'API). Mise à jour du moteur : dans le conteneur, comme sur un serveur dédié, puis
`--only pbx` réapplique la marque et le NAT.

**Stockage objet.** Une installation neuve utilise SeaweedFS (`nimbora_seaweedfs`). Une installation qui avait déjà MinIO le garde (`OBJECT_STORE=minio` écrit par le kit) ; pour passer à SeaweedFS : `OBJECT_STORE=seaweedfs` dans `/opt/nimbora-lab/.env`, relancer `--only nimbora`, puis `copy`, `verify`, `switch` (voir `docs/deployment/object-storage.mdx`), et enfin `MINIO_RETIRED=true` et relancer : MinIO n'est plus démarré.

**Quelle version tourne ?** Les images portent le commit dont elles sont construites :

```bash
curl -s https://app.example.com/api/v1/health | python3 -m json.tool | grep build_commit
git -C ~/nimbora log --oneline -1          # doit commencer par la même empreinte
```

`install.sh` construit les images sous le nom que la pile utilise (`REGISTRY` du `.env`,
`nimbora` par défaut) et compare à la fin le commit de l'API en service avec celui du dépôt :
« image non reconstruite ? » signale une API restée sur une version précédente (par exemple
après `--no-build`, ou une image construite à la main sous un autre nom). Construire à la
main demande `sudo` (ou le groupe `docker`) :

```bash
sudo docker build --build-arg GIT_COMMIT=$(git rev-parse --short=7 HEAD) \
    -f api/Dockerfile -t "$(sudo grep -E '^REGISTRY=' /opt/nimbora-lab/.env | cut -d= -f2 || echo nimbora)/nimbora-api:latest" .
```

## 6. Retirer le laboratoire

```bash
sudo rm /data/coolify/proxy/dynamic/nimbora-lab.yaml      # Traefik oublie les deux noms
(cd /opt/nimbora-lab && sudo docker compose down -v)        # pile et données NIMBORA
sudo incus delete -f nimbora-pbx                           # PBX
sudo systemctl disable --now nimbora-lab-firewall && sudo rm /etc/systemd/system/nimbora-lab-firewall.service /usr/local/sbin/nimbora-lab-firewall
sudo iptables -S DOCKER-USER | grep nimbora-lab | sed 's/^-A/-D/' | xargs -rL1 sudo iptables
sudo iptables -t nat -S PREROUTING | grep nimbora-lab | sed 's/^-A/-D/' | xargs -rL1 sudo iptables -t nat
```

Incus et ses paquets peuvent rester ou être retirés (`apt-get remove incus`).

## 7. Limites

- Un seul serveur partage CPU et mémoire entre le PBX, la plateforme et le reste : réservé
  aux tests, aux démonstrations et à de petites équipes.
- Le PBX est en NAT derrière l'hôte : l'adresse publique est inscrite sur ses transports
  SIP (`pbx_nat.py`). Un second PBX sur le même hôte demanderait une seconde IP publique.
- L'IA locale (Ollama, Whisper) n'est pas déployée ; branchez des fournisseurs (clés dans
  `--secrets-file`) ou un serveur d'IA séparé (`LOCAL_LLM_BASE_URL`, `LOCAL_SPEECH_BASE_URL`).

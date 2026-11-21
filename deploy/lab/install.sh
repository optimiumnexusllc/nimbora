#!/usr/bin/env bash
# NIMBORA lab — the white-label PBX and the AI platform on ONE shared server.
#
# For validating phase 5 (and demos) without a dedicated Debian 12 machine: the
# PBX engine runs in an Incus system container (Debian 12), the NIMBORA stack
# runs in Docker Compose behind the server's existing Traefik (Coolify), and the
# host only gets the glue: Incus, firewall rules between Docker and Incus, the
# RTP redirection to the PBX, one Traefik dynamic file. Nothing already running
# on the server is stopped or changed.
#
#   sudo ./install.sh --app-domain app.example.com --pbx-domain pbx.example.com \
#        --brand NIMBORA --company "Entreprise test" [--secrets-file /root/keys.env]
#
# Re-runnable: each phase checks what exists. Phases: preflight, incus, firewall,
# pbx, nimbora, traefik, summary. Run some only: --only incus,firewall.
# Parameters are saved in /etc/nimbora-lab/lab.env (see lab.env.example).
set -euo pipefail

KIT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$KIT_DIR/../.." && pwd)"
STATE_DIR=/etc/nimbora-lab
LAB_ENV="$STATE_DIR/lab.env"
FIREWALL_BIN=/usr/local/sbin/nimbora-lab-firewall
UNIT=nimbora-lab-firewall.service

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ✓ \033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m ⚠ \033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERREUR :\033[0m %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

# ---------------------------------------------------------------- parameters
# Defaults < saved lab.env < flags.
APP_DOMAIN="" PBX_DOMAIN="" BRAND="NIMBORA" COMPANY="Entreprise test"
PUBLIC_IF="" PUBLIC_IP=""
INCUS_BRIDGE=incusbr0 BRIDGE_CIDR=10.250.0.1/24 PBX_IP=10.250.0.10
PBX_NAME=nimbora-pbx PBX_MEMORY=4GiB PBX_CPU=2
TRAEFIK_DYNAMIC_DIR=/data/coolify/proxy/dynamic TRAEFIK_NETWORK=coolify
DEPLOY_DIR=/opt/nimbora-lab NIMBORA_BRIDGE=br-nimboralab NIMBORA_SUBNET=10.250.1.0/24
FASTAPI_WORKERS=2 SECRETS_FILE=""
RTP_RANGE=10000-20000 SIP_PUBLIC=0 UFW=0
ONLY="" BUILD=1 FORCE_PBX=0

# shellcheck disable=SC1090
[[ -f "$LAB_ENV" ]] && . "$LAB_ENV"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app-domain) APP_DOMAIN="$2"; shift 2 ;;
        --pbx-domain) PBX_DOMAIN="$2"; shift 2 ;;
        --brand) BRAND="$2"; shift 2 ;;
        --company) COMPANY="$2"; shift 2 ;;
        --public-if) PUBLIC_IF="$2"; shift 2 ;;
        --public-ip) PUBLIC_IP="$2"; shift 2 ;;
        --bridge-cidr) BRIDGE_CIDR="$2"; shift 2 ;;
        --pbx-ip) PBX_IP="$2"; shift 2 ;;
        --pbx-memory) PBX_MEMORY="$2"; shift 2 ;;
        --pbx-cpu) PBX_CPU="$2"; shift 2 ;;
        --traefik-dynamic-dir) TRAEFIK_DYNAMIC_DIR="$2"; shift 2 ;;
        --traefik-network) TRAEFIK_NETWORK="$2"; shift 2 ;;
        --deploy-dir) DEPLOY_DIR="$2"; shift 2 ;;
        --workers) FASTAPI_WORKERS="$2"; shift 2 ;;
        --secrets-file) SECRETS_FILE="$2"; shift 2 ;;
        --rtp-range) RTP_RANGE="$2"; shift 2 ;;
        --sip-public) SIP_PUBLIC=1; shift ;;
        --no-sip-public) SIP_PUBLIC=0; shift ;;
        --ufw) UFW=1; shift ;;
        --only) ONLY="$2"; shift 2 ;;
        --no-build) BUILD=0; shift ;;
        --force-pbx) FORCE_PBX=1; shift ;;
        -h|--help) usage ;;
        *) echo "Option inconnue : $1"; usage 1 ;;
    esac
done

[[ $EUID -eq 0 ]] || die "À lancer en root (sudo)."
[[ -n "$APP_DOMAIN" && -n "$PBX_DOMAIN" ]] || die "--app-domain et --pbx-domain sont requis."
[[ "$RTP_RANGE" =~ ^[0-9]+-[0-9]+$ ]] || die "--rtp-range attend début-fin (ex. 10000-20000)."
[[ "$FASTAPI_WORKERS" =~ ^[1-9][0-9]*$ ]] || die "--workers attend un entier positif."

runs() { [[ -z "$ONLY" ]] || [[ ",$ONLY," == *",$1,"* ]]; }

# Without --secrets-file, a file at the default place is picked up as soon as
# it exists, whichever phases run: drop it there later and re-run `--only nimbora`.
DEFAULT_SECRETS_FILE="$STATE_DIR/secrets.env"
[[ -n "$SECRETS_FILE" ]] || SECRETS_FILE="$DEFAULT_SECRETS_FILE"

# set_kv FILE KEY VALUE — replace or append KEY=VALUE (value quoted if needed)
set_kv() {
    local file=$1 key=$2 value=$3 tmp
    [[ "$value" =~ [[:space:]\#\"\'] ]] && value="\"${value//\"/\\\"}\""
    tmp="$(mktemp)"
    if [[ -f "$file" ]]; then
        awk -v k="$key" -v v="$value" 'BEGIN{d=0} $0 ~ "^"k"=" {print k"="v; d=1; next} {print} END{if(!d) print k"="v}' "$file" > "$tmp"
    else
        echo "$key=$value" > "$tmp"
    fi
    cat "$tmp" > "$file"; rm -f "$tmp"
}
get_kv() { grep -E "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }
ensure_secret() {  # ensure_secret FILE KEY [generator]
    [[ -n "$(get_kv "$1" "$2")" ]] || set_kv "$1" "$2" "$(${3:-openssl rand -hex 32})"
}
bridge_gateway() { echo "${BRIDGE_CIDR%/*}"; }
bridge_network() {  # 10.250.0.1/24 -> 10.250.0.0/24 (only /24 handled, enough here)
    local ip=${BRIDGE_CIDR%/*} prefix=${BRIDGE_CIDR#*/}
    [[ "$prefix" == 24 ]] || die "--bridge-cidr doit être un /24"
    echo "${ip%.*}.0/24"
}

# ---------------------------------------------------------------- preflight
if runs preflight; then
    log "Préparation"
    command -v docker >/dev/null || die "Docker est requis (la pile NIMBORA et Traefik tournent dessus)."
    docker info >/dev/null 2>&1 || die "Le démon Docker ne répond pas."
    [[ -z "$PUBLIC_IF" ]] && PUBLIC_IF="$(ip -4 route show default | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')"
    [[ -n "$PUBLIC_IF" ]] || die "Interface publique introuvable, passez --public-if."
    [[ -z "$PUBLIC_IP" ]] && PUBLIC_IP="$(ip -4 -o addr show dev "$PUBLIC_IF" scope global | awk '{print $4}' | cut -d/ -f1 | head -1)"
    [[ -n "$PUBLIC_IP" ]] || die "IPv4 publique introuvable sur $PUBLIC_IF, passez --public-ip."
    docker network inspect "$TRAEFIK_NETWORK" >/dev/null 2>&1 || die "Réseau Docker « $TRAEFIK_NETWORK » introuvable (celui de Traefik)."
    TRAEFIK_BRIDGE="$(docker network inspect "$TRAEFIK_NETWORK" -f '{{index .Options "com.docker.network.bridge.name"}}')"
    [[ -n "$TRAEFIK_BRIDGE" ]] || TRAEFIK_BRIDGE="br-$(docker network inspect "$TRAEFIK_NETWORK" -f '{{.Id}}' | cut -c1-12)"
    ip link show "$TRAEFIK_BRIDGE" >/dev/null 2>&1 || die "Pont $TRAEFIK_BRIDGE absent pour le réseau $TRAEFIK_NETWORK."
    [[ -d "$TRAEFIK_DYNAMIC_DIR" ]] || die "Dossier dynamique Traefik introuvable : $TRAEFIK_DYNAMIC_DIR"
    for d in "$APP_DOMAIN" "$PBX_DOMAIN"; do
        resolved="$(getent ahostsv4 "$d" | awk '{print $1}' | sort -u | tr '\n' ' ')"
        [[ " $resolved" == *" $PUBLIC_IP "* ]] || warn "$d ne pointe pas (encore) vers $PUBLIC_IP : $resolved"
    done
    avail_mb="$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)"
    (( avail_mb >= 7000 )) || warn "Seulement ${avail_mb} Mo disponibles ; le PBX (${PBX_MEMORY}) et la pile NIMBORA (~3 Go) seront serrés."
    [[ -z "$SECRETS_FILE" || -f "$SECRETS_FILE" ]] || die "Fichier de secrets introuvable : $SECRETS_FILE"

    install -d -m 700 "$STATE_DIR"
    for k in APP_DOMAIN PBX_DOMAIN BRAND COMPANY PUBLIC_IF PUBLIC_IP INCUS_BRIDGE BRIDGE_CIDR PBX_IP PBX_NAME \
             PBX_MEMORY PBX_CPU TRAEFIK_DYNAMIC_DIR TRAEFIK_NETWORK TRAEFIK_BRIDGE DEPLOY_DIR NIMBORA_BRIDGE \
             NIMBORA_SUBNET FASTAPI_WORKERS SECRETS_FILE RTP_RANGE SIP_PUBLIC UFW; do
        set_kv "$LAB_ENV" "$k" "${!k}"
    done
    chmod 600 "$LAB_ENV"
    ok "Interface $PUBLIC_IF ($PUBLIC_IP), Traefik sur $TRAEFIK_NETWORK ($TRAEFIK_BRIDGE), paramètres dans $LAB_ENV"
else
    # shellcheck disable=SC1090
    . "$LAB_ENV" 2>/dev/null || die "Lancez d'abord la phase preflight."
fi

# -------------------------------------------------------------------- incus
if runs incus; then
    log "Incus"
    if ! command -v incus >/dev/null; then
        apt-get update -q
        DEBIAN_FRONTEND=noninteractive apt-get install -yq incus
    fi
    systemctl enable --now incus >/dev/null
    # systemd in many containers exhausts the default inotify budget.
    cat > /etc/sysctl.d/90-nimbora-lab.conf <<'EOF'
# NIMBORA lab: system containers (Incus) need more inotify instances.
fs.inotify.max_user_instances = 1024
fs.inotify.max_user_watches = 1048576
EOF
    sysctl -q -p /etc/sysctl.d/90-nimbora-lab.conf
    incus storage show default >/dev/null 2>&1 || incus storage create default dir
    if ! incus network show "$INCUS_BRIDGE" >/dev/null 2>&1; then
        incus network create "$INCUS_BRIDGE" ipv4.address="$BRIDGE_CIDR" ipv4.nat=true ipv6.address=none
    fi
    incus profile device show default | grep -q '^root:' || incus profile device add default root disk path=/ pool=default >/dev/null
    incus profile device show default | grep -q '^eth0:' || incus profile device add default eth0 nic network="$INCUS_BRIDGE" name=eth0 >/dev/null
    ok "Incus $(incus version | head -1), pont $INCUS_BRIDGE ($BRIDGE_CIDR), stockage dir"
fi

# ----------------------------------------------------------------- firewall
if runs firewall; then
    log "Pare-feu hôte : règles Docker/Incus et redirection RTP (persistantes)"
    install -m 755 "$KIT_DIR/firewall.sh" "$FIREWALL_BIN"
    install -m 644 "$KIT_DIR/templates/$UNIT" "/etc/systemd/system/$UNIT"
    systemctl daemon-reload
    systemctl enable "$UNIT" >/dev/null
    systemctl restart "$UNIT"
    ok "$(systemctl show -p ExecMainStatus --value "$UNIT" | sed 's/^0$/règles appliquées/')"
    if [[ "$UFW" == "1" ]]; then
        log "UFW (option : hébergeur sans pare-feu externe)"
        command -v ufw >/dev/null || { apt-get update -q; DEBIAN_FRONTEND=noninteractive apt-get install -yq ufw; }
        # Docker publishes its ports through its own NAT rules, UFW must let
        # forwarded traffic through or every published port breaks.
        sed -i 's/^DEFAULT_FORWARD_POLICY=.*/DEFAULT_FORWARD_POLICY="ACCEPT"/' /etc/default/ufw
        ufw --force reset >/dev/null
        ufw default deny incoming >/dev/null; ufw default allow outgoing >/dev/null
        for rule in 22/tcp 80/tcp 443/tcp 443/udp 3478/tcp 3478/udp 5349/tcp 5349/udp \
                    "49152:49200/udp" "${RTP_RANGE/-/:}/udp"; do ufw allow "$rule" >/dev/null; done
        [[ "$SIP_PUBLIC" == "1" ]] && { ufw allow 5060/udp >/dev/null; ufw allow 5060/tcp >/dev/null; ufw allow 5061/tcp >/dev/null; }
        ufw --force enable >/dev/null
        ok "UFW actif : $(ufw status | grep -c ALLOW) règles"
    fi
fi

# ---------------------------------------------------------------------- pbx
if runs pbx; then
    log "PBX : conteneur Incus $PBX_NAME (Debian 12, $PBX_CPU vCPU, $PBX_MEMORY)"
    if ! incus info "$PBX_NAME" >/dev/null 2>&1; then
        incus launch images:debian/12 "$PBX_NAME" \
            -c limits.memory="$PBX_MEMORY" -c limits.cpu="$PBX_CPU" -c boot.autostart=true \
            -d eth0,ipv4.address="$PBX_IP"
    else
        incus config set "$PBX_NAME" limits.memory="$PBX_MEMORY" limits.cpu="$PBX_CPU" boot.autostart=true
        [[ "$(incus info "$PBX_NAME" | awk '/^Status:/{print $2}')" == "RUNNING" ]] || incus start "$PBX_NAME"
    fi
    for _ in $(seq 1 60); do
        incus exec "$PBX_NAME" -- getent hosts deb.debian.org >/dev/null 2>&1 && break
        sleep 2
    done
    incus exec "$PBX_NAME" -- getent hosts deb.debian.org >/dev/null 2>&1 || die "Le conteneur $PBX_NAME n'a pas de réseau."
    incus exec "$PBX_NAME" -- bash -c 'command -v git >/dev/null && command -v curl >/dev/null' \
        || incus exec "$PBX_NAME" -- bash -c 'apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -yq git curl ca-certificates python3'
    # The kit of this checkout, so local fixes apply before they are pushed.
    incus exec "$PBX_NAME" -- mkdir -p /opt/nimbora/deploy
    incus file push -r -q "$REPO_DIR/deploy/pbx" "$PBX_NAME/opt/nimbora/deploy/"
    incus file push -q "$KIT_DIR/scripts/pbx_nat.py" "$PBX_NAME/opt/nimbora/deploy/pbx/pbx_nat.py"
    if [[ "$FORCE_PBX" == "1" ]] || ! incus exec "$PBX_NAME" -- test -f /etc/nimbora-pbx/service-account.json; then
        log "Installation du moteur dans le conteneur (20 à 40 minutes)"
        incus exec "$PBX_NAME" --env NIMBORA_URL="https://$APP_DOMAIN" -- bash -c \
            "cd /opt/nimbora/deploy/pbx && ./install.sh --brand '$BRAND' --nimbora-url https://$APP_DOMAIN --nimbora-ip $(bridge_gateway) --company '$COMPANY'"
    else
        ok "Moteur déjà installé (compte de service présent) ; --force-pbx pour relancer l'installateur"
    fi
    log "NAT d'Asterisk : adresse publique $PUBLIC_IP, réseau local $(bridge_network), RTP $RTP_RANGE"
    incus exec "$PBX_NAME" -- bash -c \
        "set -a; . /etc/nimbora-pbx/secrets.env; set +a; python3 /opt/nimbora/deploy/pbx/pbx_nat.py --insecure --root-password \"\$ROOT_PASSWORD\" --public-ip $PUBLIC_IP --local-net $(bridge_network) --rtp-range $RTP_RANGE"
    incus file pull -q "$PBX_NAME/etc/nimbora-pbx/secrets.env" "$STATE_DIR/pbx-secrets.env"
    incus file pull -q "$PBX_NAME/etc/nimbora-pbx/service-account.json" "$STATE_DIR/pbx-service-account.json"
    chmod 600 "$STATE_DIR/pbx-secrets.env" "$STATE_DIR/pbx-service-account.json"
    ok "PBX prêt sur $PBX_IP ; secrets copiés dans $STATE_DIR (root)"
fi

# ------------------------------------------------------------------ nimbora
if runs nimbora; then
    log "Pile NIMBORA dans $DEPLOY_DIR (Docker Compose, sans ports publics sauf TURN)"
    install -d -m 750 "$DEPLOY_DIR" "$DEPLOY_DIR/certs"
    cp "$REPO_DIR/docker-compose.yaml" "$DEPLOY_DIR/docker-compose.yaml"
    # nimbora-init mounts ./scripts and ./deploy to render coturn's configuration.
    rm -rf "$DEPLOY_DIR/scripts" "$DEPLOY_DIR/deploy"
    cp -r "$REPO_DIR/scripts" "$DEPLOY_DIR/scripts"
    install -d "$DEPLOY_DIR/deploy"; cp -r "$REPO_DIR/deploy/templates" "$DEPLOY_DIR/deploy/templates"
    sed -e "s#__NIMBORA_BRIDGE__#$NIMBORA_BRIDGE#" -e "s#__NIMBORA_SUBNET__#$NIMBORA_SUBNET#" \
        -e "s#__TRAEFIK_NETWORK__#$TRAEFIK_NETWORK#" \
        "$KIT_DIR/templates/docker-compose.override.yaml" > "$DEPLOY_DIR/docker-compose.override.yaml"

    ENV="$DEPLOY_DIR/.env"
    [[ -f "$ENV" ]] || { umask 077; : > "$ENV"; }
    set_kv "$ENV" COMPOSE_PROJECT_NAME nimbora-lab
    set_kv "$ENV" COMPOSE_PROFILES local-turn
    set_kv "$ENV" ENVIRONMENT production
    set_kv "$ENV" SERVER_IP "$PUBLIC_IP"
    set_kv "$ENV" PUBLIC_HOST "$APP_DOMAIN"
    set_kv "$ENV" PUBLIC_BASE_URL "https://$APP_DOMAIN"
    set_kv "$ENV" ENABLE_COTURN true
    set_kv "$ENV" FASTAPI_WORKERS "$FASTAPI_WORKERS"
    set_kv "$ENV" ENABLE_TELEMETRY false
    set_kv "$ENV" BRAND_NAME "$BRAND"
    set_kv "$ENV" BRAND_PBX_NAME "$BRAND Voice"
    set_kv "$ENV" BRAND_DOMAIN "${APP_DOMAIN#*.}"
    ensure_secret "$ENV" TURN_SECRET
    ensure_secret "$ENV" OSS_JWT_SECRET
    ensure_secret "$ENV" POSTGRES_PASSWORD
    ensure_secret "$ENV" REDIS_PASSWORD
    ensure_secret "$ENV" MINIO_ROOT_USER "echo nimbora$(openssl rand -hex 6)"
    ensure_secret "$ENV" MINIO_ROOT_PASSWORD
    ensure_secret "$ENV" TELEPHONY_WS_TOKEN_SECRET
    if [[ -f "$SECRETS_FILE" ]]; then
        while IFS= read -r line; do
            [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
            set_kv "$ENV" "${line%%=*}" "$(echo "${line#*=}" | sed -e 's/^"//' -e 's/"$//')"
        done < "$SECRETS_FILE"
        ok "Variables de $SECRETS_FILE fusionnées dans .env"
    else
        warn "Aucun fichier de secrets ($SECRETS_FILE) : la pile démarre sans variable supplémentaire."
        warn "Les clés des fournisseurs d'IA (Deepgram, Groq, Google AI Studio…) se saisissent dans la console,"
        warn "Fournisseurs d'inférence → Ajouter une connexion ; sans elles, aucun agent IA ne peut répondre."
        warn "Pour des variables d'environnement (SMTP, options…), créez $SECRETS_FILE puis relancez --only nimbora."
    fi
    chmod 600 "$ENV"

    if [[ "$BUILD" == "1" ]]; then
        log "Construction des images (longue sur un petit serveur ; --no-build pour la sauter)"
        docker build -q -f "$REPO_DIR/api/Dockerfile" -t nimbora/nimbora-api:latest "$REPO_DIR" >/dev/null
        ok "image nimbora/nimbora-api:latest"
        docker build -q -f "$REPO_DIR/ui/Dockerfile" -t nimbora/nimbora-ui:latest "$REPO_DIR" >/dev/null
        ok "image nimbora/nimbora-ui:latest"
    fi
    (cd "$DEPLOY_DIR" && docker compose up -d --remove-orphans)
    # The stack's bridge now exists: re-apply the firewall so its rules bind to it.
    systemctl restart "$UNIT"
    ok "Pile démarrée : $(cd "$DEPLOY_DIR" && docker compose ps --format '{{.Name}} {{.Status}}' | tr '\n' ';')"
fi

# ------------------------------------------------------------------ traefik
if runs traefik; then
    log "Traefik : routage de $APP_DOMAIN et $PBX_DOMAIN (fichier dynamique, Let's Encrypt)"
    servers=""
    for ((p = 8000; p < 8000 + FASTAPI_WORKERS; p++)); do
        servers+="          - url: http://nimbora_api:$p"$'\n'
    done
    target="$TRAEFIK_DYNAMIC_DIR/nimbora-lab.yaml"
    tmp="$(mktemp)"
    awk -v servers="$servers" '{ if ($0 == "__API_SERVERS__") printf "%s", servers; else print }' \
        "$KIT_DIR/templates/traefik-nimbora-lab.yaml" \
        | sed -e "s#__APP_DOMAIN__#$APP_DOMAIN#g" -e "s#__PBX_DOMAIN__#$PBX_DOMAIN#g" -e "s#__PBX_IP__#$PBX_IP#g" > "$tmp"
    if [[ -f "$target" ]] && cmp -s "$tmp" "$target"; then
        rm -f "$tmp"; ok "$target déjà à jour"
    else
        install -m 644 "$tmp" "$target"; rm -f "$tmp"   # atomic from Traefik's point of view
        ok "$target écrit (Traefik le recharge seul)"
    fi
    for d in "$APP_DOMAIN" "$PBX_DOMAIN"; do
        for _ in $(seq 1 30); do
            issuer="$(echo | openssl s_client -servername "$d" -connect "127.0.0.1:443" 2>/dev/null | openssl x509 -noout -issuer 2>/dev/null || true)"
            [[ "$issuer" == *"Let's Encrypt"* ]] && break
            sleep 4
        done
        [[ "$issuer" == *"Let's Encrypt"* ]] && ok "Certificat Let's Encrypt pour $d" || warn "Pas encore de certificat Let's Encrypt pour $d (DNS ? port 80 ?)"
    done
fi

# ------------------------------------------------------------------ summary
if runs summary; then
    cat <<EOF

============================================================
 NIMBORA lab : $APP_DOMAIN (plateforme) et $PBX_DOMAIN (PBX)

 Ports à ouvrir chez l'hébergeur (IPv4, vers ce serveur) :
   22/tcp SSH · 80/tcp 443/tcp 443/udp Web · 3478/tcp+udp 5349/tcp+udp 49152-49200/udp TURN
   ${RTP_RANGE}/udp RTP (audio des téléphones)$( [[ "$SIP_PUBLIC" == "1" ]] && echo " · 5060/udp 5060/tcp 5061/tcp SIP" || echo " · SIP 5060/5061 fermé (--sip-public quand un opérateur est raccordé)")

 Dans ${BRAND} → Téléphonie → Ajouter → Asterisk ARI (agents IA) :
   Endpoint ARI       : http://${PBX_IP}:5039   (réseau privé, jamais public)
   Utilisateur ARI    : xivo
   Mot de passe ARI   : ARI_PASSWORD dans ${STATE_DIR}/pbx-secrets.env
   websocket client   : nimbora

 Dans ${BRAND} → Téléphonie d'entreprise → Connexion :
   Adresse du PBX     : https://${PBX_IP}  (certificat non vérifié) ou https://${PBX_DOMAIN}
   Compte de service  : nimbora-integration
   Mot de passe       : SERVICE_PASSWORD dans ${STATE_DIR}/pbx-secrets.env
   Tenant             : ${STATE_DIR}/pbx-service-account.json
   Softphones         : Postes → Softphones → adresse wss://${PBX_DOMAIN}/api/asterisk/ws

 Exploitation :
   incus exec ${PBX_NAME} -- wazo-service status
   (cd ${DEPLOY_DIR} && docker compose ps)
   systemctl status ${UNIT}
============================================================
EOF
fi

#!/usr/bin/env bash
# Install the white-label PBX (Wazo Platform engine, GPL-3.0) on a dedicated
# Debian 12 server, rebrand it and prepare it for the AI platform.
#
#   sudo ./install.sh --brand "NIMBORA" --nimbora-url https://app.example.com \
#        --nimbora-ip 203.0.113.10 --company "Ivoire Immo" [--support-email ...] \
#        [--ssh-from CIDR,…] [--sip-from CIDR,…|any|none] [--phones-from CIDR,…] \
#        [--rtp-range 10000-20000] [--firewall-only]
#
# Firewall: only SSH, HTTPS, SIP/RTP (from --sip-from, default any) and the ARI
# from the platform are open; everything else the engine listens on is closed.
# Re-runnable: secrets are generated once in /etc/nimbora-pbx/secrets.env.
# --firewall-only re-applies the firewall alone (after changing its options).
set -euo pipefail

BRAND="NIMBORA"
PBX_NAME=""
NIMBORA_URL=""
NIMBORA_IP=""
COMPANY="my-company"
SUPPORT_EMAIL=""
NOREPLY_EMAIL=""
ARI_TLS_CERT=""
ARI_TLS_KEY=""
ENGINE_VERSION="stable"
SSH_FROM="any"
SIP_FROM="any"
PHONES_FROM="none"
RTP_RANGE="10000-20000"
FIREWALL_ONLY=0
KIT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR=/etc/nimbora-pbx
WORK_DIR=/opt/nimbora-pbx

usage() { sed -n '2,14p' "$0"; exit 1; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --brand) BRAND="$2"; shift 2 ;;
    --pbx-name) PBX_NAME="$2"; shift 2 ;;
    --nimbora-url) NIMBORA_URL="${2%/}"; shift 2 ;;
    --nimbora-ip) NIMBORA_IP="$2"; shift 2 ;;
    --company) COMPANY="$2"; shift 2 ;;
    --support-email) SUPPORT_EMAIL="$2"; shift 2 ;;
    --noreply-email) NOREPLY_EMAIL="$2"; shift 2 ;;
    --ari-tls-cert) ARI_TLS_CERT="$2"; shift 2 ;;
    --ari-tls-key) ARI_TLS_KEY="$2"; shift 2 ;;
    --engine-version) ENGINE_VERSION="$2"; shift 2 ;;
    --ssh-from) SSH_FROM="$2"; shift 2 ;;
    --sip-from) SIP_FROM="$2"; shift 2 ;;
    --phones-from) PHONES_FROM="$2"; shift 2 ;;
    --rtp-range) RTP_RANGE="$2"; shift 2 ;;
    --firewall-only) FIREWALL_ONLY=1; shift ;;
    -h|--help) usage ;;
    *) echo "Option inconnue : $1"; usage ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "À lancer en root (sudo)."; exit 1; }
[[ -n "$NIMBORA_URL" && -n "$NIMBORA_IP" ]] || { echo "--nimbora-url et --nimbora-ip sont requis."; usage; }
grep -q 'VERSION_CODENAME=bookworm' /etc/os-release || { echo "Debian 12 (bookworm) requis."; exit 1; }
[[ "$COMPANY" != *[\"\'\\]* ]] || { echo "--company ne peut contenir ni guillemet ni barre oblique inverse."; exit 1; }
[[ "$RTP_RANGE" =~ ^[0-9]+-[0-9]+$ ]] || { echo "--rtp-range attend début-fin (ex. 10000-20000)."; exit 1; }
for v in SSH_FROM SIP_FROM PHONES_FROM; do
  [[ "${!v}" =~ ^(any|none|([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?(,([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?)*)$ ]] \
    || { flag="${v,,}"; echo "--${flag//_/-} attend any, none ou des adresses IPv4/CIDR séparées par des virgules."; exit 1; }
done

# One nftables rule per source list: "any" opens to everyone, "none" writes
# nothing, a CIDR list restricts to those IPv4 sources.
nft_rule() {  # nft_rule SOURCES RULE…
  local src=$1; shift
  case "$src" in
    none) ;;
    any) printf '    %s\n' "$*" ;;
    *) printf '    ip saddr { %s } %s\n' "${src//,/, }" "$*" ;;
  esac
}

# Everything the engine listens on and that is not listed here (RabbitMQ 5672,
# 25672 and 15672, epmd 4369, Postfix 25, SCCP 2000, wazo-phoned 9498/9499,
# provd 8667, HTTP 80, the internal REST services) stays reachable from the
# server itself only. Loopback, replies, ICMP and the DHCP lease stay allowed.
apply_firewall() {
  echo "==> Pare-feu : tout fermé sauf SSH, HTTPS, SIP/RTP et l'ARI depuis la plateforme"
  cat > /etc/nftables.d-nimbora-pbx.conf <<EOF
# NIMBORA PBX kit (deploy/pbx/install.sh): the only ports open from outside.
table inet nimbora_pbx {
  chain input {
    type filter hook input priority -10; policy drop;
    iif lo accept
    ct state established,related accept
    ct state invalid drop
    meta l4proto { icmp, ipv6-icmp } accept
    udp sport 67 udp dport 68 accept
$(nft_rule "$SSH_FROM" "tcp dport 22 accept")
    tcp dport 443 accept
    tcp dport 5039 ip saddr { 127.0.0.1, ${NIMBORA_IP} } accept
    tcp dport 5038 ip saddr 127.0.0.1 accept
    tcp dport { 5038, 5039 } ip6 saddr ::1 accept
$(nft_rule "$SIP_FROM" "udp dport 5060 accept")
$(nft_rule "$SIP_FROM" "tcp dport { 5060, 5061 } accept")
$(nft_rule "$SIP_FROM" "udp dport ${RTP_RANGE} accept")
$(nft_rule "$PHONES_FROM" "tcp dport { 8667, 9498, 9499 } accept")
  }
}
EOF
  grep -q 'nftables.d-nimbora-pbx.conf' /etc/nftables.conf || echo 'include "/etc/nftables.d-nimbora-pbx.conf"' >> /etc/nftables.conf
  systemctl enable --now nftables >/dev/null
  nft -f /etc/nftables.conf
}

if [[ "$FIREWALL_ONLY" == 1 ]]; then
  command -v nft >/dev/null || { apt-get update -q; DEBIAN_FRONTEND=noninteractive apt-get install -yq nftables; }
  apply_firewall
  nft list table inet nimbora_pbx
  exit 0
fi

# The engine's installer runs `wazo-auth-cli tenant create {{ tenant_name }}`
# unquoted: a company name with a space ("Ivoire Immo") would be split into two
# arguments and the tenant creation fails. Written as a Python literal holding
# the quotes, the inventory value reaches the command as one argument.
ansible_quote() { printf "'\"%s\"'" "$1"; }
[[ "${NIMBORA_URL}" == https://* ]] || echo "⚠ ${NIMBORA_URL} n'est pas en HTTPS : l'audio des agents IA circulera en clair."

DOMAIN="${NIMBORA_URL#https://}"; DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN%%/*}"; DOMAIN="${DOMAIN%%:*}"
PBX_NAME="${PBX_NAME:-$BRAND Voice}"
SUPPORT_EMAIL="${SUPPORT_EMAIL:-support@$DOMAIN}"
NOREPLY_EMAIL="${NOREPLY_EMAIL:-noreply@$DOMAIN}"
WS_URL="${NIMBORA_URL/https:/wss:}"; WS_URL="${WS_URL/http:/ws:}/api/v1/telephony/ws/ari"

echo "==> Paquets de base"
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -yq sudo git ansible curl openssl python3 nftables locales
locale -a | grep -qi 'utf-8\|utf8' || { sed -i 's/^# *\(fr_FR.UTF-8\)/\1/' /etc/locale.gen; locale-gen; }

echo "==> Secrets (générés une seule fois, jamais les valeurs par défaut de l'installateur)"
install -d -m 700 "$STATE_DIR"
if [[ ! -f "$STATE_DIR/secrets.env" ]]; then
  gen() { openssl rand -base64 33 | tr -d '/+=' | cut -c1-32; }
  umask 077
  cat > "$STATE_DIR/secrets.env" <<EOF
POSTGRES_PASSWORD=$(gen)
DB_AUTH_PASSWORD=$(gen)
DB_CONFD_PASSWORD=$(gen)
ARI_PASSWORD=$(gen)
AMI_PASSWORD=$(gen)
ROOT_PASSWORD=$(gen)
API_CLIENT_PASSWORD=$(gen)
SERVICE_PASSWORD=$(gen)
EOF
fi
# shellcheck disable=SC1091
source "$STATE_DIR/secrets.env"

echo "==> Installateur du moteur (version ${ENGINE_VERSION})"
install -d "$WORK_DIR"
if [[ ! -d "$WORK_DIR/engine-installer/.git" ]]; then
  git clone -q https://github.com/wazo-platform/wazo-ansible.git "$WORK_DIR/engine-installer"
fi
cd "$WORK_DIR/engine-installer"
git fetch -q --tags
if [[ "$ENGINE_VERSION" == "stable" ]]; then
  ENGINE_VERSION="$(curl -fsS https://mirror.wazo.community/version/stable)"
fi
git checkout -q "wazo-${ENGINE_VERSION}"
ansible-galaxy install -r requirements-postgresql.yml

ARI_TLS_VARS=""
if [[ -n "$ARI_TLS_CERT" && -n "$ARI_TLS_KEY" ]]; then
  ARI_TLS_VARS="b2bua_https_cert = ${ARI_TLS_CERT}
b2bua_https_private_key = ${ARI_TLS_KEY}"
fi

umask 077
cat > "$WORK_DIR/inventory.ini" <<EOF
[all:vars]
ansible_python_interpreter = /usr/bin/python3

[uc_engine_host]
localhost ansible_connection=local

[database:children]
uc_engine_host

[engine_api:children]
uc_engine_host

[b2bua:children]
uc_engine_host

[uc_engine:children]
b2bua
database
engine_api

# No [uc_ui] group: the engine's own web UI is never installed (white label).

[uc_engine:vars]
wazo_distribution = pelican-bookworm
wazo_distribution_upgrade = pelican-bookworm
engine_language = fr_FR
tenant_name = $(ansible_quote "$COMPANY")
engine_api_configure_wizard = true
engine_api_root_password = ${ROOT_PASSWORD}
api_client_name = api-client
api_client_password = ${API_CLIENT_PASSWORD}
postgresql_superuser_password = ${POSTGRES_PASSWORD}
engine_api_db_admin_password = ${POSTGRES_PASSWORD}
engine_api_db_auth_password = ${DB_AUTH_PASSWORD}
engine_api_db_confd_password = ${DB_CONFD_PASSWORD}
ari_password = ${ARI_PASSWORD}
ami_password = ${AMI_PASSWORD}
# ARI must be reachable by the AI platform (firewalled to it below). The
# engine's b2bua role writes http.d/10-engine-api.conf only when BOTH the
# address and the port are defined; without the port Asterisk stays on
# 127.0.0.1 and the platform gets "connection refused".
b2bua_listen_address = 0.0.0.0
b2bua_port_http = 5039
${ARI_TLS_VARS}
EOF

echo "==> Installation du moteur (20 à 40 minutes)"
ansible-playbook -i "$WORK_DIR/inventory.ini" uc-engine.yml

echo "==> Marque blanche"
cat > "$STATE_DIR/branding.yml" <<EOF
brand_name: "${BRAND}"
pbx_name: "${PBX_NAME}"
support_email: "${SUPPORT_EMAIL}"
noreply_email: "${NOREPLY_EMAIL}"
nimbora_url: "${NIMBORA_URL}"
nimbora_ws_url: "${WS_URL}"
pbx_root_password: "${ROOT_PASSWORD}"
EOF
chmod 600 "$STATE_DIR/branding.yml"
cd "$KIT_DIR"
ansible-playbook -i "$WORK_DIR/inventory.ini" whitelabel.yml -e "@$STATE_DIR/branding.yml"

apply_firewall

echo "==> Compte de service de la plateforme (droits minimaux)"
python3 "$KIT_DIR/scripts/create_service_account.py" --url https://localhost --insecure \
  --root-password "$ROOT_PASSWORD" --tenant-name "$COMPANY" --password "$SERVICE_PASSWORD" \
  | tee "$STATE_DIR/service-account.json"

PUBLIC_IP="$(hostname -I | awk '{print $1}')"
cat <<EOF

============================================================
 ${PBX_NAME} est installé.

 Dans ${BRAND} → Téléphonie d'entreprise → Connexion :
   Adresse du PBX     : https://<nom-de-ce-serveur>
   Compte de service  : nimbora-integration
   Mot de passe       : voir SERVICE_PASSWORD dans ${STATE_DIR}/secrets.env
   Tenant             : voir ${STATE_DIR}/service-account.json

 Dans ${BRAND} → Téléphonie → Ajouter → Asterisk ARI (agents IA) :
   Endpoint ARI       : http://${PUBLIC_IP}:5039   (https si --ari-tls-cert)
   Utilisateur ARI    : xivo
   Mot de passe ARI   : voir ARI_PASSWORD dans ${STATE_DIR}/secrets.env
   websocket client   : nimbora

 Secrets : ${STATE_DIR}/secrets.env (root uniquement). Sauvegardez-le.
============================================================
EOF

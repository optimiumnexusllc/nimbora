#!/usr/bin/env bash
# NIMBORA Enterprise — VPS installer (Ubuntu 22.04 / 24.04, Debian 12).
#
#   sudo ./install.sh --domain callcenter.example.com --email admin@example.com
#
# Idempotent: re-running keeps existing secrets and data.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

DOMAIN=""
EMAIL=""
PROFILE=""
SKIP_FIREWALL=0
NO_START=0

usage() {
  sed -n '2,7p' "$0"
  echo "Options: --domain D --email E [--gpu] [--skip-firewall] [--no-start]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --email) EMAIL="$2"; shift 2 ;;
    --gpu) PROFILE="gpu"; shift ;;
    --skip-firewall) SKIP_FIREWALL=1; shift ;;
    --no-start) NO_START=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

rand() { openssl rand -hex "${1:-32}"; }

set_env() {  # set_env KEY VALUE — replace or append in .env
  local key="$1" value="$2"
  if grep -qE "^${key}=" .env; then
    local escaped
    escaped=$(printf '%s' "$value" | sed -e 's/[\/&|]/\\&/g')
    sed -i -E "s|^${key}=.*|${key}=${escaped}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

get_env() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//'; }

ensure_secret() {  # keep an existing value, otherwise generate one
  local key="$1" len="${2:-32}"
  if [[ -z "$(get_env "$key")" ]]; then
    set_env "$key" "$(rand "$len")"
  fi
}

# ------------------------------------------------------------------ 1. Docker
if ! command -v docker >/dev/null 2>&1; then
  [[ $EUID -eq 0 ]] || die "Run as root (sudo) to install Docker"
  log "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"

# ------------------------------------------------------------------- 2. .env
if [[ ! -f .env ]]; then
  log "Creating .env"
  cp .env.example .env
  chmod 600 .env
fi

[[ -n "$DOMAIN" ]] && { set_env PUBLIC_HOST "$DOMAIN"; set_env PUBLIC_BASE_URL "https://$DOMAIN"; }
[[ -n "$EMAIL" ]] && set_env ACME_EMAIL "$EMAIL"
[[ -n "$PROFILE" ]] && set_env COMPOSE_PROFILES "$PROFILE"

PUBLIC_HOST="$(get_env PUBLIC_HOST)"
[[ "$PUBLIC_HOST" == "callcenter.example.com" || -z "$PUBLIC_HOST" ]] && die "Pass --domain your.domain (DNS must point to this server)"
[[ "$(get_env ACME_EMAIL)" == "admin@example.com" ]] && die "Pass --email for Let's Encrypt"

PUBLIC_IP="$(get_env PUBLIC_IP)"
if [[ -z "$PUBLIC_IP" || "$PUBLIC_IP" == "203.0.113.10" ]]; then
  PUBLIC_IP="$(curl -fsS4 https://api.ipify.org || true)"
  [[ -n "$PUBLIC_IP" ]] || die "Could not detect the public IP; set PUBLIC_IP in .env"
  set_env PUBLIC_IP "$PUBLIC_IP"
fi

for key in POSTGRES_PASSWORD REDIS_PASSWORD MINIO_ROOT_PASSWORD OSS_JWT_SECRET \
           TURN_SECRET ASTERISK_ARI_PASSWORD TELEPHONY_WS_TOKEN_SECRET; do
  ensure_secret "$key"
done

# ------------------------------------------------- 3. Asterisk configuration
log "Rendering Asterisk configuration"
mkdir -p generated/asterisk
ARI_PASSWORD="$(get_env ASTERISK_ARI_PASSWORD)"
BASE_URL="$(get_env PUBLIC_BASE_URL)"
sed -e "s|__PUBLIC_IP__|${PUBLIC_IP}|g" asterisk/pjsip.conf.template > generated/asterisk/pjsip.conf
sed -e "s|__ASTERISK_ARI_PASSWORD__|${ARI_PASSWORD}|g" \
    -e "s|__PUBLIC_BASE_URL__|${BASE_URL}|g" asterisk/ari.conf.template > generated/asterisk/ari.conf
chmod 644 generated/asterisk/pjsip.conf
chmod 640 generated/asterisk/ari.conf
# Asterisk runs unprivileged in its container; let it read the ARI file.
chmod o+r generated/asterisk/ari.conf
[[ -f asterisk/pjsip_trunks.conf ]] || printf '; Carrier trunks — see README\n' > asterisk/pjsip_trunks.conf

# ---------------------------------------------------------------- 4. Firewall
if [[ $SKIP_FIREWALL -eq 0 ]] && command -v ufw >/dev/null 2>&1; then
  log "Configuring firewall (ufw)"
  ufw --force default deny incoming >/dev/null
  ufw --force default allow outgoing >/dev/null
  ufw allow 22/tcp >/dev/null            # SSH
  ufw allow 80/tcp >/dev/null            # HTTP (ACME + redirect)
  ufw allow 443/tcp >/dev/null           # HTTPS
  ufw allow 443/udp >/dev/null           # HTTP/3
  ufw allow 5060/udp >/dev/null          # SIP trunks
  ufw allow 5060/tcp >/dev/null
  ufw allow 10000:10999/udp >/dev/null   # RTP media
  ufw allow 3478 >/dev/null              # TURN
  ufw allow 49152:49300/udp >/dev/null   # TURN relay
  ufw --force enable >/dev/null
  log "Tip: restrict 5060 to your carrier's IPs: ufw allow from <IP> to any port 5060"
fi

# ------------------------------------------------------------------- 5. Start
if [[ $NO_START -eq 0 ]]; then
  log "Building and starting the platform (first build takes a while)"
  docker compose build
  docker compose up -d
  log "Downloading local AI models (voices, speech recognition, LLM)"
  ./scripts/pull_models.sh || log "Model download incomplete — re-run ./scripts/pull_models.sh"
fi

cat <<MSG

Platform ready at: $(get_env PUBLIC_BASE_URL)
 1. Create your operator account there, then grant it super-admin rights:
      ./scripts/make_superuser.sh you@example.com
 2. Super-admin console: Paramètres > Abonnements (plans, clients, quotas)
 3. Backups: ./scripts/backup.sh (add it to cron, see README)
MSG

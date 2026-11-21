#!/usr/bin/env bash
# Back up the PBX: every database of the engine, its configuration, the
# platform's kit state (secrets), voicemail, sounds and call recordings.
#
#   sudo ./scripts/backup.sh [/var/backups/nimbora-pbx]
#
# Settings (environment, or /etc/nimbora-pbx/backup.env):
#   KEEP_DAYS=14                    local backups older than this are removed
#   BACKUP_PASSPHRASE_FILE=…        encrypt the archives (AES-256, openssl)
#   BACKUP_RSYNC_TARGET=user@host:/path   copy each backup off the server
#   TEXTFILE_DIR=/var/lib/prometheus/node-exporter   freshness metric for
#                                   Prometheus (node exporter textfile)
#
# Cron, installed by install.sh: every night at 02:40.
# Restore with scripts/restore.sh <backup directory>.
set -euo pipefail

ENV_FILE="${BACKUP_ENV_FILE:-/etc/nimbora-pbx/backup.env}"
# shellcheck disable=SC1090
if [[ -f "$ENV_FILE" ]]; then source "$ENV_FILE"; fi
DEST="${1:-${BACKUP_DIR:-/var/backups/nimbora-pbx}}"
KEEP_DAYS="${KEEP_DAYS:-14}"
TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/prometheus/node-exporter}"
ROOT="${BACKUP_ROOT:-/}"   # tests point this at a fake file system
STAMP="$(date -u +%Y%m%d-%H%M%S)"
TARGET="$DEST/$STAMP"

# What the engine and the kit keep on disk (missing paths are skipped).
PATHS=(
  etc/nimbora-pbx            # kit secrets, branding, service accounts
  etc/wazo-auth etc/wazo-confd etc/wazo-calld etc/wazo-agentd etc/wazo-amid
  etc/wazo-call-logd etc/wazo-webhookd etc/wazo-dird etc/wazo-chatd
  etc/wazo-websocketd etc/wazo-plugind etc/wazo-provd etc/wazo-phoned
  etc/wazo-confgend etc/wazo-sysconfd etc/wazo-ui etc/wazo-setupd
  etc/asterisk               # dialplan, nimbora-supervision, websocket client
  etc/fail2ban/jail.d etc/fail2ban/filter.d
  etc/nftables.d-nimbora-pbx.conf
  etc/nginx/sites-available etc/ssl/private etc/letsencrypt
  var/lib/wazo               # sounds, provisioning, plugins
  var/lib/wazo-provd
  var/spool/asterisk/voicemail
  var/spool/asterisk/monitor  # call recordings
  var/lib/asterisk/moh
)

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*"; }

metric() {  # metric NAME VALUE — Prometheus textfile collector
  if [[ ! -d "$TEXTFILE_DIR" ]]; then return 0; fi
  local file="$TEXTFILE_DIR/nimbora_pbx_backup.prom"
  {
    if [[ -f "$file" ]]; then grep -v -e "^$1 " -e "^# TYPE $1 " "$file" || true; fi
    printf '# TYPE %s gauge\n%s %s\n' "$1" "$1" "$2"
  } > "$file.tmp"
  mv "$file.tmp" "$file"
}

encrypt() {  # encrypt FILE — in place, FILE becomes FILE.enc
  if [[ -z "${BACKUP_PASSPHRASE_FILE:-}" ]]; then return 0; fi
  openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$BACKUP_PASSPHRASE_FILE" \
    -in "$1" -out "$1.enc"
  rm -f "$1"
}

trap 'metric nimbora_pbx_backup_last_failure_timestamp_seconds "$(date +%s)"; log "backup FAILED"' ERR

umask 077
mkdir -p "$TARGET"
chmod 700 "$DEST"

log "databases (pg_dumpall)"
# --clean --if-exists: the dump recreates each database on restore.
sudo -u postgres pg_dumpall --clean --if-exists > "$TARGET/databases.sql"
gzip -9 "$TARGET/databases.sql"

log "configuration, voicemail, sounds, recordings"
present=()
for path in "${PATHS[@]}"; do
  if [[ -e "$ROOT/$path" ]]; then present+=("$path"); fi
done
tar -C "$ROOT" -czf "$TARGET/files.tar.gz" "${present[@]}"

engine="$(dpkg-query -W -f='${Version}' wazo-platform 2>/dev/null || echo unknown)"
cat > "$TARGET/manifest.json" <<JSON
{"created_at": "$(date -u +%FT%TZ)", "host": "$(hostname)", "engine_version": "$engine",
 "paths": [$(printf '"%s",' "${present[@]}" | sed 's/,$//')],
 "encrypted": $([[ -n "${BACKUP_PASSPHRASE_FILE:-}" ]] && echo true || echo false)}
JSON

encrypt "$TARGET/databases.sql.gz"
encrypt "$TARGET/files.tar.gz"
(cd "$TARGET" && sha256sum -- *.gz* > SHA256SUMS)

if [[ -n "${BACKUP_RSYNC_TARGET:-}" ]]; then
  log "off-site copy to $BACKUP_RSYNC_TARGET"
  rsync -a "$TARGET" "$BACKUP_RSYNC_TARGET/"
fi

find "$DEST" -mindepth 1 -maxdepth 1 -type d -mtime "+$KEEP_DAYS" -exec rm -rf {} +

size="$(du -sb "$TARGET" | cut -f1)"
metric nimbora_pbx_backup_last_success_timestamp_seconds "$(date +%s)"
metric nimbora_pbx_backup_last_size_bytes "$size"
log "backup done: $TARGET ($size bytes)"

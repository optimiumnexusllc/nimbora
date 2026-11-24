#!/usr/bin/env bash
# Nightly backup of the platform: PostgreSQL dump, the object store (call
# recordings, transcripts, documents: SeaweedFS, and MinIO on installs made
# before while it still holds files) and configuration.
#   ./scripts/backup.sh [/var/backups/nimbora]
# Cron (03:15 every night):
#   15 3 * * * /opt/nimbora/deploy/enterprise/scripts/backup.sh >> /var/log/nimbora-backup.log 2>&1
#
# Settings (environment, or backup.env next to docker-compose.yml):
#   KEEP_DAYS=14                    local backups older than this are removed
#   BACKUP_PASSPHRASE_FILE=…        encrypt the archives (AES-256, openssl)
#   BACKUP_RSYNC_TARGET=user@host:/path   copy each backup off the server
#   TEXTFILE_DIR=/var/lib/prometheus/node-exporter   freshness metric for
#                                   Prometheus (node exporter textfile)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# shellcheck disable=SC1091
if [[ -f backup.env ]]; then source backup.env; fi
DEST="${1:-${BACKUP_DIR:-/var/backups/nimbora}}"
KEEP_DAYS="${KEEP_DAYS:-14}"
TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/prometheus/node-exporter}"
SEAWEEDFS_VOLUME="${SEAWEEDFS_VOLUME:-nimbora-enterprise_seaweedfs_data}"
MINIO_VOLUME="${MINIO_VOLUME:-nimbora-enterprise_minio_data}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
TARGET="$DEST/$STAMP"

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*"; }

metric() {  # metric NAME VALUE — Prometheus textfile collector
  if [[ ! -d "$TEXTFILE_DIR" ]]; then return 0; fi
  local file="$TEXTFILE_DIR/nimbora_platform_backup.prom"
  {
    if [[ -f "$file" ]]; then grep -v -e "^$1 " -e "^# TYPE $1 " "$file" || true; fi
    printf '# TYPE %s gauge\n%s %s\n' "$1" "$1" "$2"
  } > "$file.tmp"
  mv "$file.tmp" "$file"
}

encrypt() {  # encrypt FILE — FILE becomes FILE.enc
  if [[ -z "${BACKUP_PASSPHRASE_FILE:-}" ]]; then return 0; fi
  openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$BACKUP_PASSPHRASE_FILE" \
    -in "$1" -out "$1.enc"
  rm -f "$1"
}

trap 'metric nimbora_platform_backup_last_failure_timestamp_seconds "$(date +%s)"; log "backup FAILED"' ERR

umask 077
mkdir -p "$TARGET"
chmod 700 "$DEST"

log "database"
docker compose exec -T postgres pg_dump -U postgres -Fc postgres > "$TARGET/postgres.dump"

files=(postgres.dump)
for store in seaweedfs minio; do
  volume="$SEAWEEDFS_VOLUME"
  if [[ $store == minio ]]; then volume="$MINIO_VOLUME"; fi
  if docker volume inspect "$volume" > /dev/null 2>&1; then
    log "object store ($store)"
    docker run --rm \
      -v "$volume":/data:ro \
      -v "$TARGET":/backup \
      alpine tar czf "/backup/$store.tar.gz" -C /data .
    files+=("$store.tar.gz")
  fi
done
if [[ ${#files[@]} == 1 ]]; then
  log "no object store volume ($SEAWEEDFS_VOLUME, $MINIO_VOLUME): recordings not saved"
  false
fi

log "configuration"
config=()
for path in .env backup.env generated asterisk; do
  if [[ -e "$path" ]]; then config+=("$path"); fi
done
tar czf "$TARGET/config.tar.gz" -T /dev/null "${config[@]}"

files+=(config.tar.gz)
sums=()
for file in "${files[@]}"; do
  encrypt "$TARGET/$file"
  if [[ -f "$TARGET/$file.enc" ]]; then sums+=("$file.enc"); else sums+=("$file"); fi
done
(cd "$TARGET" && sha256sum -- "${sums[@]}" > SHA256SUMS)

if [[ -n "${BACKUP_RSYNC_TARGET:-}" ]]; then
  log "off-site copy to $BACKUP_RSYNC_TARGET"
  rsync -a "$TARGET" "$BACKUP_RSYNC_TARGET/"
fi

find "$DEST" -mindepth 1 -maxdepth 1 -type d -mtime "+$KEEP_DAYS" -exec rm -rf {} +
size="$(du -sb "$TARGET" | cut -f1)"
metric nimbora_platform_backup_last_success_timestamp_seconds "$(date +%s)"
metric nimbora_platform_backup_last_size_bytes "$size"
log "backup done: $TARGET ($size bytes)"

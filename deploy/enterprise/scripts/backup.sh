#!/usr/bin/env bash
# Nightly backup: PostgreSQL dump + call recordings (MinIO) + configuration.
#   ./scripts/backup.sh [/var/backups/nimbora]
# Cron (03:15 every night, keeps 14 days):
#   15 3 * * * /opt/nimbora/deploy/enterprise/scripts/backup.sh >> /var/log/nimbora-backup.log 2>&1
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
DEST="${1:-/var/backups/nimbora}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="$DEST/$STAMP"
mkdir -p "$TARGET"
chmod 700 "$DEST"

echo "[$(date)] database"
docker compose exec -T postgres pg_dump -U postgres -Fc postgres > "$TARGET/postgres.dump"

echo "[$(date)] recordings"
docker run --rm \
  -v nimbora-enterprise_minio_data:/data:ro \
  -v "$TARGET":/backup \
  alpine tar czf /backup/minio.tar.gz -C /data .

echo "[$(date)] configuration"
tar czf "$TARGET/config.tar.gz" .env generated asterisk

find "$DEST" -mindepth 1 -maxdepth 1 -type d -mtime "+$KEEP_DAYS" -exec rm -rf {} +
echo "[$(date)] backup done: $TARGET"

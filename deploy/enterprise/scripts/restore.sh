#!/usr/bin/env bash
# Restore a backup made by backup.sh onto this server (DESTROYS current data).
#   ./scripts/restore.sh /var/backups/nimbora/20261120-031500
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
SRC="${1:?backup directory}"
read -r -p "This replaces the database and recordings. Type RESTORE to continue: " ok
[[ "$ok" == "RESTORE" ]] || exit 1
docker compose stop api ui
docker compose exec -T postgres pg_restore -U postgres -d postgres --clean --if-exists < "$SRC/postgres.dump"
docker compose stop minio
docker run --rm -v nimbora-enterprise_minio_data:/data -v "$SRC":/backup:ro alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/minio.tar.gz -C /data"
docker compose up -d
echo "Restored from $SRC"

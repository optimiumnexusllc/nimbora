#!/usr/bin/env bash
# Restore a backup made by backup.sh onto this server (REPLACES current data).
#   ./scripts/restore.sh /var/backups/nimbora/20261120-031500 [--yes]
#   ./scripts/restore.sh <dir> --check      verify the archives only
# Encrypted backups need BACKUP_PASSPHRASE_FILE (same file as for the backup).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# shellcheck disable=SC1091
if [[ -f backup.env ]]; then source backup.env; fi
SRC="${1:?backup directory}"
MODE="${2:-}"
MINIO_VOLUME="${MINIO_VOLUME:-nimbora-enterprise_minio_data}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [[ -f "$SRC/SHA256SUMS" ]]; then
  (cd "$SRC" && sha256sum --quiet -c SHA256SUMS) || { echo "Backup altered: restore refused."; exit 1; }
fi

fetch() {  # fetch NAME — plain copy in $WORK (decrypted if needed)
  if [[ -f "$SRC/$1.enc" ]]; then
    [[ -n "${BACKUP_PASSPHRASE_FILE:-}" ]] || { echo "Encrypted backup: set BACKUP_PASSPHRASE_FILE."; exit 1; }
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$BACKUP_PASSPHRASE_FILE" \
      -in "$SRC/$1.enc" -out "$WORK/$1"
  else
    cp "$SRC/$1" "$WORK/$1"
  fi
}
fetch postgres.dump
fetch minio.tar.gz
tar -tzf "$WORK/minio.tar.gz" > /dev/null
echo "Archives readable."
if [[ "$MODE" == "--check" ]]; then exit 0; fi
if [[ "$MODE" != "--yes" ]]; then
  read -r -p "This replaces the database and recordings. Type RESTORE to continue: " ok
  [[ "$ok" == "RESTORE" ]] || exit 1
fi
docker compose stop api ui
docker compose exec -T postgres pg_restore -U postgres -d postgres --clean --if-exists < "$WORK/postgres.dump"
docker compose stop minio
docker run --rm -v "$MINIO_VOLUME":/data -v "$WORK":/backup:ro alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/minio.tar.gz -C /data"
docker compose up -d
echo "Restored from $SRC"

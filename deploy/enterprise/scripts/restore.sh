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
SEAWEEDFS_VOLUME="${SEAWEEDFS_VOLUME:-nimbora-enterprise_seaweedfs_data}"
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
# The object store: seaweedfs.tar.gz, and/or minio.tar.gz (installs made before
# SeaweedFS, and every backup taken before it).
stores=()
for store in seaweedfs minio; do
  if [[ -f "$SRC/$store.tar.gz" || -f "$SRC/$store.tar.gz.enc" ]]; then
    fetch "$store.tar.gz"
    tar -tzf "$WORK/$store.tar.gz" > /dev/null
    stores+=("$store")
  fi
done
[[ ${#stores[@]} -gt 0 ]] || { echo "No object store archive in $SRC: restore refused."; exit 1; }
echo "Archives readable."
if [[ "$MODE" == "--check" ]]; then exit 0; fi
if [[ "$MODE" != "--yes" ]]; then
  read -r -p "This replaces the database and recordings. Type RESTORE to continue: " ok
  [[ "$ok" == "RESTORE" ]] || exit 1
fi
docker compose stop api ui
docker compose exec -T postgres pg_restore -U postgres -d postgres --clean --if-exists < "$WORK/postgres.dump"
for store in "${stores[@]}"; do
  volume="$SEAWEEDFS_VOLUME"
  if [[ $store == minio ]]; then
    volume="$MINIO_VOLUME"
    docker compose --profile minio stop minio
  else
    docker compose stop seaweedfs
  fi
  docker run --rm -v "$volume":/data -v "$WORK":/backup:ro alpine \
    sh -c "rm -rf /data/* && tar xzf /backup/$store.tar.gz -C /data"
done
# A restored MinIO volume holds files the database still reads from MinIO:
# keep it running (same rule as install.sh).
if [[ -f .env ]]; then
  # shellcheck source=SCRIPTDIR/object_store.sh
  source scripts/object_store.sh
  enterprise_object_store .env docker > /dev/null
fi
docker compose up -d
echo "Restored from $SRC"

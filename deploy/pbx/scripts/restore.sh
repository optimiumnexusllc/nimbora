#!/usr/bin/env bash
# Restore a backup made by backup.sh (REPLACES the PBX's data).
#
#   sudo ./scripts/restore.sh /var/backups/nimbora-pbx/20261121-024000 [--yes]
#   sudo ./scripts/restore.sh <dir> --check     verify the archives only
#
# On a new server: install the same engine version with install.sh first
# (manifest.json gives it), then restore. Encrypted backups need
# BACKUP_PASSPHRASE_FILE (same file as for the backup).
set -euo pipefail

ENV_FILE="${BACKUP_ENV_FILE:-/etc/nimbora-pbx/backup.env}"
# shellcheck disable=SC1090
if [[ -f "$ENV_FILE" ]]; then source "$ENV_FILE"; fi
SRC="${1:?répertoire de sauvegarde}"
MODE="${2:-}"
ROOT="${BACKUP_ROOT:-/}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*"; }

[[ -f "$SRC/SHA256SUMS" && -f "$SRC/manifest.json" ]] || { echo "Pas une sauvegarde du PBX : $SRC"; exit 1; }
log "integrity (SHA256SUMS)"
(cd "$SRC" && sha256sum --quiet -c SHA256SUMS) || { echo "Sauvegarde altérée : restauration refusée."; exit 1; }

decrypt() {  # decrypt NAME — into $WORK/NAME
  if [[ -f "$SRC/$1.enc" ]]; then
    [[ -n "${BACKUP_PASSPHRASE_FILE:-}" ]] || { echo "Sauvegarde chiffrée : BACKUP_PASSPHRASE_FILE requis."; exit 1; }
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$BACKUP_PASSPHRASE_FILE" \
      -in "$SRC/$1.enc" -out "$WORK/$1"
  else
    cp "$SRC/$1" "$WORK/$1"
  fi
}
decrypt databases.sql.gz
decrypt files.tar.gz
gzip -t "$WORK/databases.sql.gz"
tar -tzf "$WORK/files.tar.gz" > /dev/null
log "archives readable: $(tar -tzf "$WORK/files.tar.gz" | wc -l) files"
cat "$SRC/manifest.json"; echo

if [[ "$MODE" == "--check" ]]; then
  log "check only: nothing restored"
  exit 0
fi
if [[ "$MODE" != "--yes" ]]; then
  read -r -p "Les bases et la configuration du PBX vont être remplacées. Tapez RESTAURER : " ok
  [[ "$ok" == "RESTAURER" ]] || exit 1
fi

log "stopping the engine"
wazo-service stop
log "databases"
gunzip -c "$WORK/databases.sql.gz" | sudo -u postgres psql -q -v ON_ERROR_STOP=0 -d postgres > "$WORK/psql.log" 2>&1 || true
grep -E "^ERROR|FATAL" "$WORK/psql.log" | grep -v "already exists\|does not exist\|current user cannot be dropped" | head -20 || true
log "files"
tar -C "$ROOT" -xzpf "$WORK/files.tar.gz"
log "starting the engine"
wazo-service start
if command -v nft >/dev/null && [[ -f "$ROOT/etc/nftables.conf" ]]; then nft -f "$ROOT/etc/nftables.conf" || true; fi
log "restored from $SRC"

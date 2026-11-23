"""Platform backup and restore (deploy/enterprise/scripts), with a stub docker."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2]
BACKUP = DEPLOY / "enterprise" / "scripts" / "backup.sh"
RESTORE = DEPLOY / "enterprise" / "scripts" / "restore.sh"

DOCKER = r"""#!/usr/bin/env bash
echo "docker $*" >> "$LOG"
if [[ "$1" == compose && "$2" == exec ]]; then
  if [[ " $* " == *" pg_dump "* ]]; then printf 'PGDMP-fake-dump'; else cat > "$WORK_DIR/restored.dump"; fi
  exit 0
fi
if [[ "$1" == run ]]; then
  for arg in "$@"; do
    case "$arg" in *:/backup|*:/backup:ro) backup="${arg%%:/backup*}" ;; esac
  done
  if [[ " $* " == *" czf "* ]]; then
    mkdir -p "$WORK_DIR/minio/nimbora"; echo recording > "$WORK_DIR/minio/nimbora/call.wav"
    tar czf "$backup/minio.tar.gz" -C "$WORK_DIR/minio" .
  else
    mkdir -p "$WORK_DIR/minio-restored"; tar xzf "$backup/minio.tar.gz" -C "$WORK_DIR/minio-restored"
  fi
fi
"""


@pytest.fixture
def env(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(DOCKER)
    docker.chmod(0o755)
    (tmp_path / "textfile").mkdir()
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LOG": str(tmp_path / "docker.log"),
        "WORK_DIR": str(tmp_path),
        "TEXTFILE_DIR": str(tmp_path / "textfile"),
    }


def run(script: Path, *args: str, env: dict, check=True, **extra):
    return subprocess.run(
        ["bash", str(script), *args],
        env={**env, **extra},
        capture_output=True,
        text=True,
        check=check,
    )


def test_backup_restore_round_trip_with_encryption(tmp_path, env):
    key = tmp_path / "key"
    key.write_text("platform passphrase\n")
    dest = tmp_path / "backups"
    run(BACKUP, str(dest), env=env, BACKUP_PASSPHRASE_FILE=str(key))
    (backup,) = list(dest.iterdir())
    assert sorted(p.name for p in backup.iterdir()) == [
        "SHA256SUMS",
        "config.tar.gz.enc",
        "minio.tar.gz.enc",
        "postgres.dump.enc",
    ]
    assert b"PGDMP" not in (backup / "postgres.dump.enc").read_bytes()
    metric = (tmp_path / "textfile" / "nimbora_platform_backup.prom").read_text()
    assert "nimbora_platform_backup_last_success_timestamp_seconds" in metric

    checked = run(
        RESTORE, str(backup), "--check", env=env, BACKUP_PASSPHRASE_FILE=str(key)
    )
    assert "Archives readable." in checked.stdout
    run(RESTORE, str(backup), "--yes", env=env, BACKUP_PASSPHRASE_FILE=str(key))
    assert (tmp_path / "restored.dump").read_text() == "PGDMP-fake-dump"
    assert (
        tmp_path / "minio-restored" / "nimbora" / "call.wav"
    ).read_text() == "recording\n"
    log = (tmp_path / "docker.log").read_text()
    assert (
        log.index("compose stop api ui")
        < log.index("pg_restore")
        < log.index("compose up -d")
    )


def test_restore_refuses_an_altered_backup(tmp_path, env):
    dest = tmp_path / "backups"
    run(BACKUP, str(dest), env=env)
    (backup,) = list(dest.iterdir())
    with open(backup / "postgres.dump", "ab") as dump:
        dump.write(b"!")
    result = run(RESTORE, str(backup), "--yes", env=env, check=False)
    assert result.returncode != 0 and "altered" in result.stdout
    assert "pg_restore" not in (tmp_path / "docker.log").read_text()

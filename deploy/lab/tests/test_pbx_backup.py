"""PBX backup and restore (deploy/pbx/scripts/backup.sh, restore.sh).

Run for real against a fake file system and stub commands (sudo, pg_dumpall,
psql, wazo-service, rsync): archives, encryption, integrity check, retention,
Prometheus freshness metric and the order of the restore steps.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2]
BACKUP = DEPLOY / "pbx" / "scripts" / "backup.sh"
RESTORE = DEPLOY / "pbx" / "scripts" / "restore.sh"


@pytest.fixture
def pbx(tmp_path: Path):
    """A fake PBX: file system, stub commands, a log of what ran."""
    root = tmp_path / "root"
    for rel, content in {
        "etc/nimbora-pbx/secrets.env": "ROOT_PASSWORD=s3cret\n",
        "etc/asterisk/extensions_extra.d/nimbora-supervision.conf": "[nimbora-supervision]\n",
        "etc/wazo-auth/conf.d/50-nimbora.yml": "brand: NIMBORA\n",
        "var/spool/asterisk/voicemail/default/1001/INBOX/msg0000.wav": "RIFF",
        "var/spool/asterisk/monitor/2026/11/21/call.wav": "RIFF-recording",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    stubs = {
        # sudo -u postgres CMD… → CMD…
        "sudo": 'shift 2; exec "$@"',
        "pg_dumpall": f'echo "pg_dumpall $*" >> {log}; echo "CREATE DATABASE asterisk;"',
        "psql": f'echo "psql $*" >> {log}; cat >> {tmp_path}/restored.sql',
        "wazo-service": f'echo "wazo-service $*" >> {log}',
        "dpkg-query": "echo 26.11",
        "rsync": f'echo "rsync $*" >> {log}; mkdir -p "${{@: -1}}"; cp -r "${{@: -2:1}}" "${{@: -1}}"',
        "nft": "true",
    }
    for name, body in stubs.items():
        script = bin_dir / name
        script.write_text(f"#!/usr/bin/env bash\n{body}\n")
        script.chmod(0o755)

    textfile = tmp_path / "textfile"
    textfile.mkdir()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(root),
        "BACKUP_ENV_FILE": str(tmp_path / "absent.env"),
        "TEXTFILE_DIR": str(textfile),
    }

    class Pbx:
        pass

    p = Pbx()
    p.tmp, p.root, p.env, p.log, p.textfile = tmp_path, root, env, log, textfile
    p.dest = tmp_path / "backups"

    def run(script: Path, *args: str, check=True, **extra):
        return subprocess.run(
            ["bash", str(script), *args],
            env={**env, **extra},
            capture_output=True,
            text=True,
            check=check,
        )

    p.run = run
    return p


def _only_backup(dest: Path) -> Path:
    (backup,) = [d for d in dest.iterdir() if d.is_dir()]
    return backup


def test_backup_contains_databases_configuration_and_recordings(pbx):
    pbx.run(BACKUP, str(pbx.dest))
    backup = _only_backup(pbx.dest)
    names = sorted(p.name for p in backup.iterdir())
    assert names == ["SHA256SUMS", "databases.sql.gz", "files.tar.gz", "manifest.json"]
    assert "pg_dumpall --clean --if-exists" in pbx.log.read_text()

    listing = subprocess.run(
        ["tar", "-tzf", str(backup / "files.tar.gz")], capture_output=True, text=True, check=True
    ).stdout
    for wanted in (
        "etc/nimbora-pbx/secrets.env",
        "etc/asterisk/extensions_extra.d/nimbora-supervision.conf",
        "var/spool/asterisk/monitor/2026/11/21/call.wav",
        "var/spool/asterisk/voicemail/default/1001/INBOX/msg0000.wav",
    ):
        assert wanted in listing
    manifest = json.loads((backup / "manifest.json").read_text())
    assert manifest["engine_version"] == "26.11" and manifest["encrypted"] is False
    assert "etc/wazo-dird" not in manifest["paths"]  # absent paths are skipped
    # Secrets inside: the backup is readable by root only.
    assert oct(backup.stat().st_mode)[-3:] == "700"

    metric = (pbx.textfile / "nimbora_pbx_backup.prom").read_text()
    assert "nimbora_pbx_backup_last_success_timestamp_seconds" in metric
    assert metric.count("# TYPE nimbora_pbx_backup_last_size_bytes gauge") == 1


def test_second_run_keeps_one_line_per_metric(pbx):
    pbx.run(BACKUP, str(pbx.dest))
    pbx.run(BACKUP, str(pbx.dest / "again"))
    metric = (pbx.textfile / "nimbora_pbx_backup.prom").read_text()
    lines = metric.splitlines()
    assert sum(line.startswith("nimbora_pbx_backup_last_success_timestamp_seconds ") for line in lines) == 1
    assert sum(line.startswith("# TYPE nimbora_pbx_backup_last_success") for line in lines) == 1


def test_encrypted_backup_round_trip_and_offsite_copy(pbx):
    passphrase = pbx.tmp / "passphrase"
    passphrase.write_text("correct horse battery staple\n")
    offsite = pbx.tmp / "offsite"
    pbx.run(
        BACKUP,
        str(pbx.dest),
        BACKUP_PASSPHRASE_FILE=str(passphrase),
        BACKUP_RSYNC_TARGET=str(offsite),
    )
    backup = _only_backup(pbx.dest)
    assert sorted(p.name for p in backup.iterdir()) == [
        "SHA256SUMS",
        "databases.sql.gz.enc",
        "files.tar.gz.enc",
        "manifest.json",
    ]
    assert b"s3cret" not in (backup / "files.tar.gz.enc").read_bytes()
    assert (offsite / backup.name / "files.tar.gz.enc").exists()

    # Without the passphrase: refused. With it: readable.
    refused = pbx.run(RESTORE, str(backup), "--check", check=False)
    assert refused.returncode != 0 and "BACKUP_PASSPHRASE_FILE" in refused.stdout
    checked = pbx.run(RESTORE, str(backup), "--check", BACKUP_PASSPHRASE_FILE=str(passphrase))
    assert "check only" in checked.stdout
    assert "wazo-service" not in pbx.log.read_text()  # nothing stopped


def test_restore_refuses_an_altered_backup(pbx):
    pbx.run(BACKUP, str(pbx.dest))
    backup = _only_backup(pbx.dest)
    with open(backup / "files.tar.gz", "ab") as archive:
        archive.write(b"tampered")
    result = pbx.run(RESTORE, str(backup), "--yes", check=False)
    assert result.returncode != 0 and "altérée" in result.stdout
    assert "wazo-service" not in pbx.log.read_text()


def test_restore_stops_engine_reloads_databases_and_files(pbx):
    pbx.run(BACKUP, str(pbx.dest))
    backup = _only_backup(pbx.dest)
    # A new, empty server.
    new_root = pbx.tmp / "new-root"
    new_root.mkdir()
    pbx.run(RESTORE, str(backup), "--yes", BACKUP_ROOT=str(new_root))

    commands = [line.split()[0:2] for line in pbx.log.read_text().splitlines()]
    order = [c for c in commands if c[0] in {"wazo-service", "psql"}]
    assert order == [["wazo-service", "stop"], ["psql", "-q"], ["wazo-service", "start"]]
    assert "CREATE DATABASE asterisk;" in (pbx.tmp / "restored.sql").read_text()
    restored = new_root / "etc/nimbora-pbx/secrets.env"
    assert restored.read_text() == "ROOT_PASSWORD=s3cret\n"
    assert (new_root / "var/spool/asterisk/monitor/2026/11/21/call.wav").exists()


def test_restore_asks_for_confirmation(pbx):
    pbx.run(BACKUP, str(pbx.dest))
    backup = _only_backup(pbx.dest)
    result = subprocess.run(
        ["bash", str(RESTORE), str(backup)],
        env=pbx.env,
        input="non\n",
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "wazo-service" not in pbx.log.read_text()


def test_failed_backup_records_its_failure(pbx):
    (pbx.tmp / "bin" / "pg_dumpall").write_text("#!/usr/bin/env bash\nexit 3\n")
    result = pbx.run(BACKUP, str(pbx.dest), check=False)
    assert result.returncode != 0
    metric = (pbx.textfile / "nimbora_pbx_backup.prom").read_text()
    assert "nimbora_pbx_backup_last_failure_timestamp_seconds" in metric
    assert "last_success" not in metric


def test_backup_covers_the_engine_state_seen_on_a_real_26_11():
    """Validated on the lab engine: service keys, DTLS keys, astdb and recordings
    directories exist and are needed to restore on a new server."""
    script = (KIT / "scripts/backup.sh").read_text() if "KIT" in globals() else (Path(__file__).resolve().parents[2] / "pbx/scripts/backup.sh").read_text()
    for path in (
        "var/lib/wazo-auth-keys", "var/lib/asterisk/keys", "var/lib/asterisk/astdb.sqlite3",
        "var/lib/asterisk/sounds", "var/spool/asterisk/recording", "var/lib/wazo-call-logd",
        "var/lib/wazo-agentd", "var/lib/wazo-chatd",
    ):
        assert path in script, path

"""Enterprise stack (deploy/enterprise): SeaweedFS by default, MinIO kept for installs made before.

Same rule as the main compose: an update never points an install at an empty
store. install.sh keeps MinIO (OBJECT_STORE=minio) where its volume exists and
writes the `minio` profile into COMPOSE_PROFILES, so the documented update and a
plain `docker compose up` both keep it running until MINIO_RETIRED=true.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.request import urlopen

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parents[2]
REPO = DEPLOY.parent
ENTERPRISE = DEPLOY / "enterprise"
HELPER = ENTERPRISE / "scripts" / "object_store.sh"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((ENTERPRISE / "docker-compose.yml").read_text())


def test_seaweedfs_is_the_default_store_and_minio_an_opt_in_profile(compose):
    services = compose["services"]
    weed = services["seaweedfs"]
    root = yaml.safe_load((REPO / "docker-compose.yaml").read_text())["services"]
    assert "profiles" not in weed
    # Same pinned image and command as the main compose (validated on the lab).
    assert weed["image"] == root["seaweedfs"]["image"]
    assert weed["command"] == root["seaweedfs"]["command"]
    assert weed["healthcheck"]["test"] == root["seaweedfs"]["healthcheck"]["test"]
    # Private bucket: the identity is the stack's own generated secret.
    assert weed["environment"] == {
        "AWS_ACCESS_KEY_ID": "${MINIO_ROOT_USER:?}",
        "AWS_SECRET_ACCESS_KEY": "${MINIO_ROOT_PASSWORD:?}",
    }
    assert "ports" not in weed  # reached only through Caddy
    assert weed["networks"] == ["internal"]
    assert "seaweedfs_data:/data" in weed["volumes"]
    assert "seaweedfs_data" in compose["volumes"]
    assert "minio_data" in compose["volumes"]  # kept: existing installs' files

    assert services["minio"]["profiles"] == ["minio"]
    api = services["api"]
    assert api["environment"]["OBJECT_STORE"] == "${OBJECT_STORE:-seaweedfs}"
    # Files still recorded on MinIO stay readable through these.
    assert api["environment"]["MINIO_ENDPOINT"] == "minio:9000"
    assert api["depends_on"]["seaweedfs"] == {"condition": "service_healthy"}
    assert api["depends_on"]["minio"] == {
        "condition": "service_healthy",
        "required": False,
    }
    assert services["caddy"]["environment"]["OBJECT_STORE"] == (
        "${OBJECT_STORE:-seaweedfs}"
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(directory: Path, port: int) -> HTTPServer:
    server = HTTPServer(
        ("127.0.0.1", port), partial(SimpleHTTPRequestHandler, directory=directory)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize(
    ("store", "expected"),
    [("", "seaweedfs"), ("seaweedfs", "seaweedfs"), ("minio", "minio")],
)
def test_caddy_serves_signed_links_from_the_active_store(tmp_path, store, expected):
    """/voice-audio/ goes to the store the API signs links for."""
    caddy = shutil.which("caddy")
    if not caddy:
        pytest.skip("caddy binary not installed")
    ports = {"seaweedfs": _free_port(), "minio": _free_port()}
    servers = []
    for name, port in ports.items():
        (tmp_path / name / "voice-audio").mkdir(parents=True)
        (tmp_path / name / "voice-audio" / "call.wav").write_text(name)
        servers.append(_serve(tmp_path / name, port))
    front = _free_port()
    caddyfile = (ENTERPRISE / "Caddyfile").read_text()
    caddyfile = (
        caddyfile.replace("email {$ACME_EMAIL}", "admin off\n\tauto_https off")
        .replace("{$PUBLIC_HOST} {", f":{front} {{")
        .replace("seaweedfs:8333", f"127.0.0.1:{ports['seaweedfs']}")
        .replace("minio:9000", f"127.0.0.1:{ports['minio']}")
    )
    config = tmp_path / "Caddyfile"
    config.write_text(caddyfile)
    proc = subprocess.Popen(
        [caddy, "run", "--config", str(config), "--adapter", "caddyfile"],
        env={**os.environ, "OBJECT_STORE": store},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        body = None
        for _ in range(50):
            try:
                url = f"http://127.0.0.1:{front}/voice-audio/call.wav"
                body = urlopen(url, timeout=1).read().decode()
                break
            except OSError:
                time.sleep(0.1)
        assert body == expected
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for server in servers:
            server.shutdown()


# --------------------------------------------------- install.sh detection

DOCKER = r"""#!/usr/bin/env bash
echo "docker $*" >> "$LOG"
if [[ "$1" == volume && "$2" == inspect ]]; then
  [[ " $VOLUMES " == *" $3 "* ]] && exit 0 || exit 1
fi
"""


@pytest.fixture
def docker(tmp_path):
    stub = tmp_path / "docker"
    stub.write_text(DOCKER)
    stub.chmod(0o755)
    return stub


def detect(tmp_path, docker, env_text: str, volumes: str = "") -> tuple[str, str]:
    env_file = tmp_path / ".env"
    env_file.write_text(env_text)
    out = subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; source "$0"; enterprise_object_store "$1" "$2"',
            str(HELPER),
            str(env_file),
            str(docker),
        ],
        env={**os.environ, "LOG": str(tmp_path / "log"), "VOLUMES": volumes},
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip(), env_file.read_text()


def test_new_install_gets_seaweedfs_and_no_minio(tmp_path, docker):
    printed, env = detect(tmp_path, docker, "PUBLIC_HOST=x\nCOMPOSE_PROFILES=cpu\n")
    assert printed == ""
    assert "OBJECT_STORE=seaweedfs\n" in env
    assert "COMPOSE_PROFILES=cpu\n" in env


def test_install_made_before_keeps_minio_even_for_a_plain_compose_up(tmp_path, docker):
    printed, env = detect(
        tmp_path,
        docker,
        "COMPOSE_PROFILES=gpu\n",
        volumes="nimbora-enterprise_minio_data",
    )
    assert printed == "minio"
    assert "OBJECT_STORE=minio\n" in env
    # Written into .env: `docker compose up` reads it, not only install.sh.
    assert "COMPOSE_PROFILES=gpu,minio\n" in env
    # Idempotent.
    printed, env = detect(
        tmp_path, docker, env, volumes="nimbora-enterprise_minio_data"
    )
    assert printed == "minio" and env.count("minio") == 2


def test_minio_keeps_running_during_a_migration_then_stops_when_retired(
    tmp_path, docker
):
    volumes = "nimbora-enterprise_minio_data nimbora-enterprise_seaweedfs_data"
    printed, env = detect(
        tmp_path,
        docker,
        "OBJECT_STORE=seaweedfs\nCOMPOSE_PROFILES=cpu,minio\n",
        volumes=volumes,
    )
    assert printed == "minio" and "COMPOSE_PROFILES=cpu,minio\n" in env
    printed, env = detect(tmp_path, docker, env + "MINIO_RETIRED=true\n", volumes)
    assert printed == ""
    assert "COMPOSE_PROFILES=cpu\n" in env
    assert "OBJECT_STORE=seaweedfs\n" in env


def test_install_sh_uses_the_helper_and_stops_a_retired_minio():
    script = (ENTERPRISE / "install.sh").read_text()
    assert 'source "$HERE/scripts/object_store.sh"' in script
    assert "enterprise_object_store .env docker" in script
    # compose up does not stop a service whose profile was removed.
    stop = script.index("docker compose --profile minio rm -sf minio")
    assert stop < script.index("docker compose up -d")


def test_update_instructions_go_through_install_sh():
    readme = (ENTERPRISE / "README.md").read_text()
    assert "git pull && sudo ./install.sh" in readme
    assert "git pull && docker compose build && docker compose up -d" not in readme

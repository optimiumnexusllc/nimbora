"""Bundled object store: SeaweedFS by default, MinIO kept for installs made before.

An update must never point an install at an empty store: the scripts keep
MinIO (OBJECT_STORE=minio, `minio` profile) where a MinIO volume exists, and
MinIO keeps running during a migration until MINIO_RETIRED=true.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parents[2]
REPO = DEPLOY.parent
COMMON = REPO / "scripts" / "lib" / "setup_common.sh"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((REPO / "docker-compose.yaml").read_text())


def test_seaweedfs_is_the_default_store_and_minio_an_opt_in_profile(compose):
    services = compose["services"]
    weed = services["seaweedfs"]
    assert "profiles" not in weed  # starts with a plain `docker compose up`
    # Pinned by digest (validated on the lab, step 20), like every bundled image.
    assert weed["image"] == (
        "${SEAWEEDFS_IMAGE:-chrislusf/seaweedfs:4.55"
        "@sha256:7ca46aeae2f223b37e5d91593c17ab37738eec6df6ab69b48a0487f7643342b9}"
    )
    command = weed["command"]
    assert command[0] == "server" and "-s3" in command and "-s3.port=8333" in command
    assert "-master.telemetry=false" in command  # no anonymous statistics
    # Its admin identity (private bucket) is the bundled store's keys.
    assert weed["environment"] == {
        "AWS_ACCESS_KEY_ID": "${MINIO_ROOT_USER:-minioadmin}",
        "AWS_SECRET_ACCESS_KEY": "${MINIO_ROOT_PASSWORD:-minioadmin}",
    }
    assert weed["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "-fsS",
        "http://127.0.0.1:8333/healthz",
    ]
    assert (
        "seaweedfs-data:/data" in weed["volumes"]
        and "seaweedfs-data" in compose["volumes"]
    )
    assert all(p.startswith("127.0.0.1:") for p in weed["ports"])

    assert services["minio"]["profiles"] == ["minio"]
    api = services["api"]
    assert api["environment"]["OBJECT_STORE"] == "${OBJECT_STORE:-seaweedfs}"
    assert api["depends_on"]["seaweedfs"] == {"condition": "service_healthy"}
    assert api["depends_on"]["minio"] == {
        "condition": "service_healthy",
        "required": False,
    }
    assert (
        services["nimbora-init"]["environment"]["OBJECT_STORE"]
        == "${OBJECT_STORE:-seaweedfs}"
    )


def _compose_services(*profiles: str) -> set[str] | None:
    if not shutil.which("docker"):
        return None
    env = {
        **os.environ,
        "OSS_JWT_SECRET": "test",
        "COMPOSE_PROFILES": ",".join(profiles),
    }
    out = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(REPO / "docker-compose.yaml"),
            "config",
            "--services",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    return set(out.stdout.split()) if out.returncode == 0 else None


def test_docker_compose_resolves_both_modes():
    default, legacy = _compose_services(), _compose_services("minio")
    if default is None or legacy is None:
        pytest.skip("docker compose unavailable")
    assert "seaweedfs" in default and "minio" not in default
    assert {"seaweedfs", "minio", "api"} <= legacy


def _profiles(tmp_path: Path, env: str, volumes: str) -> tuple[str, str]:
    env_file = tmp_path / ".env"
    env_file.write_text(env)
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(f"#!/bin/sh\nprintf '%s' '{volumes}'\n")
    fake_docker.chmod(0o755)
    out = subprocess.run(
        [
            "bash",
            "-c",
            f'. "{COMMON}"; nimbora_object_store_profiles "{env_file}" "{fake_docker}"',
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return out, env_file.read_text()


@pytest.mark.parametrize(
    ("env", "volumes", "profile", "store"),
    [
        ("A=1\n", "nimbora_postgres_data\n", "", "seaweedfs"),  # new install
        (
            "A=1\n",
            "nimbora_minio-data\nnimbora_postgres_data\n",
            "minio",
            "minio",
        ),  # made before
        (
            "OBJECT_STORE=seaweedfs\n",
            "nimbora_minio-data\n",
            "minio",
            "seaweedfs",
        ),  # migrating
        (
            "OBJECT_STORE=seaweedfs\nMINIO_RETIRED=true\n",
            "nimbora_minio-data\n",
            "",
            "seaweedfs",
        ),
        ("OBJECT_STORE=minio\n", "", "minio", "minio"),  # chosen explicitly
    ],
    ids=[
        "new-install",
        "existing-minio",
        "migration",
        "minio-retired",
        "explicit-minio",
    ],
)
def test_installs_made_before_keep_their_minio(tmp_path, env, volumes, profile, store):
    printed, written = _profiles(tmp_path, env, volumes)
    assert printed == profile
    assert f"OBJECT_STORE={store}" in written


def test_nginx_serves_the_files_from_the_chosen_store(tmp_path):
    def render(store: str | None) -> str:
        env = {**os.environ, "PUBLIC_HOST": "app.example.com", "FASTAPI_WORKERS": "1"}
        env.pop("OBJECT_STORE", None)
        if store:
            env["OBJECT_STORE"] = store
        out = tmp_path / f"nginx-{store}.conf"
        subprocess.run(
            [
                "bash",
                "-c",
                f'. "{COMMON}"; nimbora_render_remote_nginx_conf "{REPO}" "{out}"',
            ],
            check=True,
            env=env,
            capture_output=True,
        )
        return out.read_text()

    assert "proxy_pass http://seaweedfs:8333/voice-audio/;" in render(None)
    assert "proxy_pass http://minio:9000/voice-audio/;" in render("minio")
    assert "__NIMBORA_OBJECT_STORE__" not in render("seaweedfs")


def test_lab_kit_routes_the_audio_path_to_the_chosen_store():
    kit = (DEPLOY / "lab" / "install.sh").read_text()
    traefik = (DEPLOY / "lab" / "templates" / "traefik-nimbora-lab.yaml").read_text()
    override = (
        DEPLOY / "lab" / "templates" / "docker-compose.override.yaml"
    ).read_text()
    assert "url: __AUDIO_SERVER__" in traefik
    assert 'audio_server="http://nimbora_seaweedfs:8333"' in kit
    assert 'audio_server="http://nimbora_minio:9000"' in kit
    assert "  seaweedfs:\n    container_name: nimbora_seaweedfs" in override
    assert "profiles+=,minio" in kit and "MINIO_RETIRED" in kit


def test_the_api_image_carries_the_migration_tool():
    """The documented `docker compose exec api python -m scripts.migrate_object_store`
    needs the tool inside the image (it was left out of the COPY list)."""
    dockerfile = (REPO / "api" / "Dockerfile").read_text()
    assert "./scripts/migrate_object_store.py" in dockerfile
    assert (REPO / "scripts" / "migrate_object_store.py").is_file()


@pytest.mark.parametrize(
    "script",
    [
        "deploy/lab/install.sh",
        "remote_up.sh",
        "scripts/start_docker.sh",
        "scripts/start_docker.ps1",
    ],
)
def test_a_retired_minio_is_stopped_not_left_running(script):
    """Lab step 20: MINIO_RETIRED=true, yet nimbora_minio kept running — `up`
    never stops a container whose profile is no longer active. Every entry
    point removes the MinIO container (never its volume) before `up`."""
    text = (REPO / script).read_text()
    assert "--profile minio rm -sf minio" in text
    assert "rm -sfv" not in text and "down -v" not in text
    assert text.index("--profile minio rm -sf minio") < text.rindex(" up ")

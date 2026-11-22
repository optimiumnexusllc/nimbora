"""Compose files: the object store image must exist and be pinned.

MinIO removed its public images; see the roadmap entry "stockage objet durable".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2]
REPO = DEPLOY.parent
COMPOSE_FILES = [
    REPO / "docker-compose.yaml",
    REPO / "docker-compose-local.yaml",
    DEPLOY / "enterprise" / "docker-compose.yml",
]


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_minio_image_is_pullable_and_health_check_has_its_alias(compose: Path):
    """MinIO removed its images from quay.io and Docker Hub (401 / pull denied).

    The default must be a build that still exists, started with an explicit
    `minio` binary (Bitnami's entrypoint executes the command as given), and
    `mc ready local` needs the `local` alias the official image used to define.
    """
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(compose.read_text())
    minio = doc["services"]["minio"]
    default_image = minio["image"].split(":-")[-1].rstrip("}")
    assert not default_image.startswith(("quay.io/minio/", "minio/", "docker.io/minio/")), default_image
    assert str(minio["command"]).startswith("minio server /data")
    assert minio["healthcheck"]["test"] == ["CMD", "mc", "ready", "local"]
    assert "MC_HOST_local" in minio["environment"]
    assert minio.get("user") == "0"


def test_minio_image_is_pinned_by_digest():
    for compose in COMPOSE_FILES:
        image = compose.read_text().split("MINIO_IMAGE:-", 1)[1].split("}", 1)[0]
        assert re.fullmatch(r"bitnamilegacy/minio:2025\.4\.22@sha256:[0-9a-f]{64}", image), image



def api_environment(compose: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(compose.read_text())["services"]["api"]["environment"]


@pytest.mark.parametrize("compose", [REPO / "docker-compose.yaml", DEPLOY / "enterprise" / "docker-compose.yml"], ids=lambda p: str(p.relative_to(REPO)))
def test_compose_passes_the_white_label_variables_to_the_api(compose: Path):
    """BRAND_* in .env reached nobody: the api service lists its environment explicitly."""
    env = api_environment(compose)
    for name in ("BRAND_NAME", "BRAND_PBX_NAME", "BRAND_DOMAIN", "BRAND_SIP_USER_AGENT"):
        assert name in env, name


@pytest.mark.parametrize("compose", [REPO / "docker-compose.yaml", DEPLOY / "enterprise" / "docker-compose.yml"], ids=lambda p: str(p.relative_to(REPO)))
def test_compose_passes_every_shared_pbx_variable_to_the_api(compose: Path):
    """Each PBX_PROVISIONING_* the API reads must be forwarded by compose."""
    constants = (REPO / "api" / "constants.py").read_text()
    names = set(re.findall(r"getenv\(\"(PBX_PROVISIONING_[A-Z_]+)\"", constants)) | set(
        re.findall(r"_env_bool\(\"(PBX_PROVISIONING_[A-Z_]+)\"", constants)
    )
    assert names, "no PBX_PROVISIONING_* in api/constants.py"
    env = api_environment(compose)
    missing = sorted(n for n in names if n not in env)
    assert not missing, missing


def test_root_compose_passes_the_saas_mode_switches_to_the_api():
    """SAAS_MODE in .env reached nobody: the operator usage report answered 404 on the lab."""
    env = api_environment(REPO / "docker-compose.yaml")
    for name in ("SAAS_MODE", "SAAS_DEFAULT_PLAN", "SAAS_TRIAL_DAYS", "SAAS_GRACE_DAYS", "SAAS_PLATFORM_NAME"):
        assert name in env, name
    assert env["SAAS_MODE"] == "${SAAS_MODE:-false}"


def test_root_compose_passes_the_private_pbx_allow_list():
    """SAAS_MODE on: every call to the lab PBX (10.250.0.10) answered 502 "pas joignable
    publiquement" until PBX_ALLOWED_HOSTS reached the container."""
    assert "PBX_ALLOWED_HOSTS" in api_environment(REPO / "docker-compose.yaml")

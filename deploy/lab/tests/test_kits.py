"""Checks on the deployment kits' shell scripts (deploy/pbx, deploy/lab).

Standard library + pytest only, no server needed: the scripts' syntax, and the
pure functions they define, exercised by sourcing the function body in bash.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2]
SCRIPTS = [
    DEPLOY / "pbx" / "install.sh",
    DEPLOY / "lab" / "install.sh",
    DEPLOY / "lab" / "firewall.sh",
]


def bash_function(script: Path, name: str, *args: str) -> str:
    """Run one function of a bash script, without executing the script itself."""
    source = script.read_text()
    # One-line definition first, then a multi-line body closed by a lone brace.
    match = re.search(rf"^{name}\(\) \{{[^\n]*\}}$", source, re.M)
    if match is None:
        match = re.search(rf"^{name}\(\)\s*\{{\n.*?^\}}", source, re.S | re.M)
    assert match, f"{name}() not found in {script}"
    cmd = match.group(0) + "\n" + " ".join([name, *(f"'{a}'" for a in args)])
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_scripts_parse(script: Path):
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_tenant_name_with_space_is_one_argument():
    """A company name with a space must reach `wazo-auth-cli tenant create` whole.

    The engine's playbook interpolates the inventory value unquoted into a
    `command:`; Ansible evaluates INI values as Python literals, so a literal
    holding double quotes is what keeps the name as a single argument.
    """
    value = bash_function(DEPLOY / "pbx" / "install.sh", "ansible_quote", "Ivoire Immo")
    assert value == "'\"Ivoire Immo\"'"
    # What Ansible will see after literal_eval, then how the command module splits it.
    import ast
    import shlex

    rendered = ast.literal_eval(value)
    assert shlex.split(f"wazo-auth-cli tenant create {rendered}") == [
        "wazo-auth-cli", "tenant", "create", "Ivoire Immo",
    ]


def test_company_name_rejects_quotes():
    source = (DEPLOY / "pbx" / "install.sh").read_text()
    assert "ne peut contenir ni guillemet" in source


def test_lab_firewall_rules_are_tagged_and_flushable():
    """Every rule the lab adds carries the comment it later removes by."""
    source = (DEPLOY / "lab" / "firewall.sh").read_text()
    inserts = [
        line for line in source.splitlines()
        if "iptables -I DOCKER-USER" in line or "iptables -t nat -I PREROUTING" in line
    ]
    assert inserts, "no iptables insert found"
    for line in inserts:
        assert '--comment "$TAG"' in line, line
    assert "flush_tagged filter DOCKER-USER" in source
    assert "flush_tagged nat PREROUTING" in source
    # First run: grep finds nothing and must not abort the script (pipefail).
    assert '|| true; }' in source


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


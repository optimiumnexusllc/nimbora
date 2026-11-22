"""/api/v1/health tells which commit the running image was built from."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_build_commit_comes_from_the_image(monkeypatch):
    from api.constants import _build_commit

    monkeypatch.setenv("NIMBORA_BUILD_COMMIT", "098737d")
    assert _build_commit() == "098737d"
    monkeypatch.setenv("NIMBORA_BUILD_COMMIT", "unknown")  # built without the argument
    assert _build_commit() is None
    monkeypatch.delenv("NIMBORA_BUILD_COMMIT")
    assert _build_commit() is None


async def test_health_reports_it(monkeypatch, test_client_factory):
    from api import constants

    monkeypatch.setattr(constants, "BUILD_COMMIT", "2248047")
    async with test_client_factory(None) as client:
        body = (await client.get("/api/v1/health")).json()
    assert body["build_commit"] == "2248047"


def test_images_and_lab_kit_carry_the_commit():
    """Both images take GIT_COMMIT; the lab kit builds under the stack's
    REGISTRY name and warns when the running API is not this checkout."""
    for dockerfile in ("api/Dockerfile", "ui/Dockerfile"):
        text = (ROOT / dockerfile).read_text()
        assert "ARG GIT_COMMIT" in text and "NIMBORA_BUILD_COMMIT=$GIT_COMMIT" in text
    kit = (ROOT / "deploy/lab/install.sh").read_text()
    assert '--build-arg GIT_COMMIT="$COMMIT"' in kit
    assert '-t "$REGISTRY_NAME/nimbora-$svc:latest"' in kit
    assert "image non reconstruite" in kit
    for workflow in ("docker-image.yml", "build-api-image.yml"):
        assert "GIT_COMMIT=" in (ROOT / ".github/workflows" / workflow).read_text()
